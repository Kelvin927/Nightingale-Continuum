"""Queue, track, and correct clinician-approved patient communications."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import append_audit
from .care import current_version
from .models import Entry, OutboundDelivery, Patient, PatientContact, User
from .policy import patient_can_read_entry

MEDICATION_OR_DOSE = re.compile(
    r"\b(?:dose|dosage|medication|medicine|tablet|capsule|mg|mcg|g|ml|lisinopril|penicillin)\b",
    re.IGNORECASE,
)
SAFE_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
SAFE_FAILURE_CODE = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\Z")
ALLOWED_TRANSITIONS = {
    "queued": {"accepted", "failed"},
    "accepted": {"delivered", "failed"},
    "failed": {"queued"},
}


@dataclass(frozen=True)
class DeliveryPolicyError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _deny(code: str, message: str) -> None:
    raise DeliveryPolicyError(code, message)


def _safe_provider_id(value: str) -> str:
    if SAFE_PROVIDER_ID.fullmatch(value):
        return value
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()[:56]}"


def queue_delivery(
    session: Session,
    *,
    actor: User,
    patient: Patient,
    entry: Entry,
    contact_id: str,
    expected_version: int,
    idempotency_key: str,
    confirm_clinical_review: bool,
    confirm_patient_identity: bool,
    confirm_medication_and_dose: bool,
    correction_for: OutboundDelivery | None = None,
) -> OutboundDelivery:
    """Create the durable outbox row in the same transaction as its audit receipt."""

    if actor.role != "clinician":
        _deny("clinician_delivery_approval_required", "A clinician must approve delivery")
    if entry.clinic_id != actor.clinic_id or patient.clinic_id != actor.clinic_id:
        _deny("delivery_tenant_mismatch", "The delivery objects do not share one clinic")
    if entry.patient_id != patient.id:
        _deny("delivery_patient_mismatch", "The entry does not belong to this patient")
    if not patient_can_read_entry(entry):
        _deny(
            "patient_release_policy_failed",
            "Only clinician-confirmed patient-facing entries can be delivered",
        )
    version = current_version(session, entry)
    if entry.current_version != expected_version:
        _deny("delivery_version_conflict", "The entry changed after delivery review")
    if not confirm_clinical_review or not confirm_patient_identity:
        _deny("delivery_attestation_incomplete", "Clinical review and identity checks are required")
    dose_sensitive = bool(MEDICATION_OR_DOSE.search(version.content))
    if dose_sensitive and not confirm_medication_and_dose:
        _deny(
            "medication_dose_attestation_required",
            "Medication and dose content requires an explicit second attestation",
        )

    contact = session.scalar(
        select(PatientContact).where(
            PatientContact.id == contact_id,
            PatientContact.patient_id == patient.id,
            PatientContact.clinic_id == actor.clinic_id,
        )
    )
    if contact is None:
        _deny("delivery_contact_not_found", "No matching patient contact route exists")
    if not contact.active or contact.verified_at is None or contact.consent_status != "granted":
        _deny(
            "delivery_contact_not_ready",
            "The contact route is inactive, unverified, or unconsented",
        )

    existing = session.scalar(
        select(OutboundDelivery).where(
            OutboundDelivery.clinic_id == actor.clinic_id,
            OutboundDelivery.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        expected_correction = None if correction_for is None else correction_for.id
        if (
            existing.source_version_id != version.id
            or existing.contact_id != contact.id
            or existing.correction_for_id != expected_correction
        ):
            _deny(
                "delivery_idempotency_collision", "The idempotency key identifies another payload"
            )
        return existing

    if correction_for is not None:
        if correction_for.clinic_id != actor.clinic_id or correction_for.patient_id != patient.id:
            _deny("correction_scope_mismatch", "The original delivery belongs to another scope")
        if correction_for.status not in {"accepted", "delivered"}:
            _deny("correction_not_sent", "Only an accepted or delivered copy can be corrected")
        active_correction = session.scalar(
            select(OutboundDelivery).where(
                OutboundDelivery.correction_for_id == correction_for.id,
                OutboundDelivery.status.in_(["queued", "accepted", "delivered"]),
            )
        )
        if active_correction is not None:
            _deny("correction_already_active", "An active correction already exists")

    delivery = OutboundDelivery(
        clinic_id=actor.clinic_id,
        patient_id=patient.id,
        source_entry_id=entry.id,
        source_version_id=version.id,
        contact_id=contact.id,
        correction_for_id=None if correction_for is None else correction_for.id,
        channel=contact.channel,
        masked_destination=contact.masked_destination,
        content_snapshot=version.content,
        content_hash=version.content_hash,
        status="queued",
        idempotency_key=idempotency_key,
        approval_evidence={
            "clinical_review": True,
            "patient_identity": True,
            "medication_and_dose": confirm_medication_and_dose,
            "dose_sensitive": dose_sensitive,
        },
        approved_by=actor.id,
    )
    session.add(delivery)
    session.flush()
    append_audit(
        session,
        clinic_id=actor.clinic_id,
        actor_id=actor.id,
        action="delivery.queued",
        object_type="outbound_delivery",
        object_id=delivery.id,
        metadata={
            "channel": delivery.channel,
            "source_version": entry.current_version,
            "dose_attested": confirm_medication_and_dose,
            "correction_for": delivery.correction_for_id,
        },
    )
    return delivery


def transition_delivery(
    session: Session,
    *,
    actor: User,
    delivery: OutboundDelivery,
    outcome: str,
    provider_message_id: str | None = None,
    failure_code: str | None = None,
    occurred_at: datetime | None = None,
) -> OutboundDelivery:
    """Apply an idempotent receipt transition without ever deleting the sent snapshot."""

    if actor.role != "admin":
        _deny(
            "delivery_receipt_admin_required", "Only the delivery control plane can record receipts"
        )
    if delivery.clinic_id != actor.clinic_id:
        _deny("delivery_tenant_mismatch", "The delivery belongs to another clinic")
    if outcome == delivery.status:
        return delivery
    if outcome not in ALLOWED_TRANSITIONS.get(delivery.status, set()):
        _deny("delivery_transition_invalid", "The requested delivery transition is not allowed")
    if outcome == "accepted" and not provider_message_id:
        _deny("provider_message_id_required", "Provider acceptance requires a message identifier")
    if outcome == "failed" and (
        failure_code is None or not SAFE_FAILURE_CODE.fullmatch(failure_code)
    ):
        _deny("delivery_failure_code_required", "A safe failure code is required")

    prior = delivery.status
    timestamp = occurred_at or datetime.now(UTC)
    delivery.status = outcome
    delivery.updated_at = timestamp
    if outcome in {"accepted", "failed"}:
        delivery.attempt_count += 1
    if outcome == "accepted":
        delivery.provider_message_id = _safe_provider_id(provider_message_id or "")
        delivery.failure_code = None
        delivery.accepted_at = timestamp
    elif outcome == "delivered":
        delivery.delivered_at = timestamp
        if delivery.correction_for_id is not None:
            original = session.get(OutboundDelivery, delivery.correction_for_id)
            if original is None or original.clinic_id != actor.clinic_id:
                _deny("correction_original_missing", "The original delivery cannot be resolved")
            original.status = "superseded"
            original.superseded_at = timestamp
            original.updated_at = timestamp
    elif outcome == "failed":
        delivery.failure_code = failure_code
    else:
        delivery.failure_code = None

    append_audit(
        session,
        clinic_id=actor.clinic_id,
        actor_id=actor.id,
        action="delivery.transitioned",
        object_type="outbound_delivery",
        object_id=delivery.id,
        metadata={
            "delivery_from_status": prior,
            "delivery_to_status": outcome,
            "channel": delivery.channel,
            "correction_for": delivery.correction_for_id,
        },
    )
    return delivery


def delivery_snapshot(session: Session, patient: Patient) -> dict:
    contacts = list(
        session.scalars(
            select(PatientContact)
            .where(PatientContact.patient_id == patient.id)
            .order_by(PatientContact.preferred.desc(), PatientContact.created_at)
        )
    )
    deliveries = list(
        session.scalars(
            select(OutboundDelivery)
            .where(OutboundDelivery.patient_id == patient.id)
            .order_by(OutboundDelivery.created_at.desc())
        )
    )
    current_versions = {
        entry.id: entry.current_version_id
        for entry in session.scalars(
            select(Entry).where(Entry.id.in_({item.source_entry_id for item in deliveries}))
        )
    }
    receipt_labels = {
        "queued": "Queued locally; not accepted by the provider",
        "accepted": "Provider accepted; patient delivery is not yet confirmed",
        "delivered": "Provider delivery receipt recorded",
        "failed": "Delivery failed; review and retry are required",
        "superseded": "Previously delivered copy; a correction was delivered",
    }
    return {
        "contacts": [
            {
                "id": contact.id,
                "channel": contact.channel,
                "masked_destination": contact.masked_destination,
                "consent_status": contact.consent_status,
                "preferred": contact.preferred,
                "active": contact.active,
                "verified": contact.verified_at is not None,
            }
            for contact in contacts
        ],
        "deliveries": [
            {
                "id": item.id,
                "source_entry_id": item.source_entry_id,
                "source_version_id": item.source_version_id,
                "source_is_current": current_versions.get(item.source_entry_id)
                == item.source_version_id,
                "correction_for_id": item.correction_for_id,
                "channel": item.channel,
                "masked_destination": item.masked_destination,
                "content_snapshot": item.content_snapshot,
                "content_hash": item.content_hash,
                "status": item.status,
                "receipt_meaning": receipt_labels[item.status],
                "attempt_count": item.attempt_count,
                "failure_code": item.failure_code,
                "approved_by": item.approved_by,
                "approval_evidence": item.approval_evidence,
                "created_at": item.created_at.isoformat(),
                "accepted_at": None if item.accepted_at is None else item.accepted_at.isoformat(),
                "delivered_at": (
                    None if item.delivered_at is None else item.delivered_at.isoformat()
                ),
                "superseded_at": (
                    None if item.superseded_at is None else item.superseded_at.isoformat()
                ),
            }
            for item in deliveries
        ],
        "safety_contract": (
            "Provider acceptance is not patient delivery. Sent snapshots remain immutable; "
            "corrections create a new approved message and preserve the original side by side."
        ),
    }
