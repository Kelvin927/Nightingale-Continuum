"""Issue and redeem channel-neutral, short-lived synthetic patient access claims."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .audit import append_audit
from .models import (
    Patient,
    PatientAccessClaim,
    PatientAccessGrant,
    PatientContact,
    User,
)
from .tenancy import bind_tenant

CLAIM_RATE_LIMIT_PER_HOUR = 3
CLAIM_MAX_ATTEMPTS = 5
SESSION_TTL_MINUTES = 30


@dataclass(frozen=True)
class AccessClaimError(ValueError):
    code: str
    message: str = "The access claim could not be verified"

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class IssuedAccessClaim:
    claim: PatientAccessClaim
    claim_token: str
    masked_destination: str
    channel: str


@dataclass(frozen=True)
class RedeemedAccessClaim:
    grant: PatientAccessGrant
    session_token: str
    actor: User


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def issue_access_claim(
    session: Session,
    *,
    actor: User,
    patient: Patient,
    contact_id: str,
    purpose: str,
    ttl_minutes: int,
    now: datetime | None = None,
) -> IssuedAccessClaim:
    timestamp = _as_utc(now or datetime.now(UTC))
    if actor.role not in {"staff", "clinician"}:
        raise AccessClaimError("access_claim_issuer_denied")
    if patient.clinic_id != actor.clinic_id:
        raise AccessClaimError("access_claim_scope_mismatch")
    contact = session.scalar(
        select(PatientContact).where(
            PatientContact.id == contact_id,
            PatientContact.clinic_id == actor.clinic_id,
            PatientContact.patient_id == patient.id,
        )
    )
    if contact is None:
        raise AccessClaimError("access_contact_not_found")
    if not contact.active or contact.verified_at is None or contact.consent_status != "granted":
        raise AccessClaimError("access_contact_not_ready")

    issued_since = timestamp - timedelta(hours=1)
    recent_count = session.scalar(
        select(func.count(PatientAccessClaim.id)).where(
            PatientAccessClaim.contact_id == contact.id,
            PatientAccessClaim.created_at >= issued_since,
        )
    )
    if (recent_count or 0) >= CLAIM_RATE_LIMIT_PER_HOUR:
        raise AccessClaimError("access_claim_rate_limited")
    for prior in session.scalars(
        select(PatientAccessClaim).where(
            PatientAccessClaim.contact_id == contact.id,
            PatientAccessClaim.status == "issued",
        )
    ):
        prior.status = "revoked"

    claim_token = secrets.token_urlsafe(24)
    claim = PatientAccessClaim(
        clinic_id=actor.clinic_id,
        patient_id=patient.id,
        contact_id=contact.id,
        token_hash=_token_hash(claim_token),
        purpose=purpose,
        status="issued",
        max_attempts=CLAIM_MAX_ATTEMPTS,
        issued_by=actor.id,
        expires_at=timestamp + timedelta(minutes=ttl_minutes),
        created_at=timestamp,
    )
    session.add(claim)
    session.flush()
    append_audit(
        session,
        clinic_id=actor.clinic_id,
        actor_id=actor.id,
        action="patient_access.claim_issued",
        object_type="patient_access_claim",
        object_id=claim.id,
        metadata={
            "channel": contact.channel,
            "access_purpose": purpose,
            "access_ttl_minutes": ttl_minutes,
        },
    )
    return IssuedAccessClaim(claim, claim_token, contact.masked_destination, contact.channel)


def redeem_access_claim(
    session: Session,
    *,
    claim_token: str,
    synthetic_record_number: str,
    date_of_birth: str,
    device_binding: str,
    now: datetime | None = None,
) -> RedeemedAccessClaim:
    timestamp = _as_utc(now or datetime.now(UTC))
    claim = session.scalar(
        select(PatientAccessClaim).where(PatientAccessClaim.token_hash == _token_hash(claim_token))
    )
    if claim is None or claim.status != "issued":
        raise AccessClaimError("access_claim_invalid")
    if _as_utc(claim.expires_at) <= timestamp:
        claim.status = "expired"
        raise AccessClaimError("access_claim_invalid")
    patient = session.scalar(
        select(Patient).where(
            Patient.id == claim.patient_id,
            Patient.clinic_id == claim.clinic_id,
        )
    )
    actor = session.scalar(
        select(User).where(
            User.clinic_id == claim.clinic_id,
            User.patient_id == claim.patient_id,
            User.role == "patient",
            User.active.is_(True),
        )
    )
    if patient is None or actor is None:
        raise AccessClaimError("access_claim_invalid")
    record_matches = hmac.compare_digest(patient.synthetic_record_number, synthetic_record_number)
    birth_matches = hmac.compare_digest(patient.date_of_birth, date_of_birth)
    if not record_matches or not birth_matches:
        claim.failed_attempts += 1
        if claim.failed_attempts >= claim.max_attempts:
            claim.status = "locked"
        append_audit(
            session,
            clinic_id=claim.clinic_id,
            actor_id=None,
            action="patient_access.claim_failed",
            object_type="patient_access_claim",
            object_id=claim.id,
            metadata={
                "access_outcome": "verification_failed",
                "access_attempt_count": claim.failed_attempts,
            },
        )
        raise AccessClaimError("access_claim_invalid")

    session_token = secrets.token_urlsafe(32)
    grant = PatientAccessGrant(
        clinic_id=claim.clinic_id,
        patient_id=claim.patient_id,
        user_id=actor.id,
        access_claim_id=claim.id,
        session_token_hash=_token_hash(session_token),
        device_binding_hash=_token_hash(device_binding),
        status="active",
        expires_at=timestamp + timedelta(minutes=SESSION_TTL_MINUTES),
        created_at=timestamp,
    )
    session.add(grant)
    claim.status = "redeemed"
    claim.redeemed_at = timestamp
    session.flush()
    append_audit(
        session,
        clinic_id=claim.clinic_id,
        actor_id=actor.id,
        action="patient_access.claim_redeemed",
        object_type="patient_access_grant",
        object_id=grant.id,
        metadata={"access_outcome": "granted", "authentication_mode": "channel_claim"},
    )
    return RedeemedAccessClaim(grant, session_token, actor)


def resolve_patient_session(
    session: Session,
    session_token: str,
    *,
    device_binding: str,
    now: datetime | None = None,
) -> User:
    timestamp = _as_utc(now or datetime.now(UTC))
    grant = session.scalar(
        select(PatientAccessGrant).where(
            PatientAccessGrant.session_token_hash == _token_hash(session_token)
        )
    )
    if grant is None or grant.status != "active" or _as_utc(grant.expires_at) <= timestamp:
        raise AccessClaimError("patient_session_invalid")
    if not hmac.compare_digest(grant.device_binding_hash, _token_hash(device_binding)):
        raise AccessClaimError("patient_session_invalid")
    actor = session.scalar(
        select(User).where(
            User.id == grant.user_id,
            User.clinic_id == grant.clinic_id,
            User.patient_id == grant.patient_id,
            User.role == "patient",
            User.active.is_(True),
        )
    )
    if actor is None:
        raise AccessClaimError("patient_session_invalid")
    bind_tenant(session, grant.clinic_id)
    return actor
