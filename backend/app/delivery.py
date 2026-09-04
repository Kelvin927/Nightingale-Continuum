"""Queue, track, and correct clinician-approved patient communications."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import NoReturn
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import append_audit
from .care import current_version
from .models import (
    CareTask,
    DeliveryFollowUp,
    Entry,
    OutboundDelivery,
    Patient,
    PatientContact,
    User,
)
from .policy import patient_can_read_entry
from .terminology import assess_medication_terminology

SAFE_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
SAFE_FAILURE_CODE = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\Z")
WEB_URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
SYNTHETIC_APPOINTMENT_PATH = re.compile(r"/synthetic/[A-Za-z0-9][A-Za-z0-9._~-]{0,127}\Z")
COMMUNICATION_PURPOSES = {"care_summary", "patient_instruction", "appointment_invitation"}
SYNTHETIC_APPOINTMENT_HOSTS = {"appointments.example.test"}
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


def _deny(code: str, message: str) -> NoReturn:
    raise DeliveryPolicyError(code, message)


def _safe_provider_id(value: str) -> str:
    if SAFE_PROVIDER_ID.fullmatch(value):
        return value
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()[:56]}"


def _appointment_link(content: str) -> str:
    links = [match.group(0).rstrip(".,;!?") for match in WEB_URL_PATTERN.finditer(content)]
    if len(links) != 1:
        _deny(
            "appointment_link_count_invalid",
            "An appointment invitation must contain exactly one HTTPS link",
        )
    link = links[0]
    try:
        parsed = urlsplit(link)
        port = parsed.port
    except ValueError:
        _deny(
            "appointment_link_not_approved",
            "The appointment link is outside the synthetic allow-listed origin and path",
        )
    if (
        parsed.scheme != "https"
        or parsed.hostname not in SYNTHETIC_APPOINTMENT_HOSTS
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or SYNTHETIC_APPOINTMENT_PATH.fullmatch(parsed.path) is None
    ):
        _deny(
            "appointment_link_not_approved",
            "The appointment link is outside the synthetic allow-listed origin and path",
        )
    return link


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _follow_up_owner_id(session: Session, actor: User) -> str:
    if actor.role != "admin":
        return actor.id
    for role in ("staff", "clinician"):
        owner_id = session.scalar(
            select(User.id)
            .where(User.clinic_id == actor.clinic_id, User.role == role)
            .order_by(User.id)
        )
        if owner_id is not None:
            return owner_id
    _deny(
        "follow_up_owner_unavailable",
        "Appointment escalation requires an active staff or clinician owner",
    )


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
    communication_purpose: str = "care_summary",
    confirm_appointment_details: bool = False,
    acknowledgement_window_minutes: int = 1_440,
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
    if communication_purpose not in COMMUNICATION_PURPOSES:
        _deny("communication_purpose_invalid", "The communication purpose is not supported")
    if not 5 <= acknowledgement_window_minutes <= 10_080:
        _deny(
            "acknowledgement_window_invalid",
            "The acknowledgement window must be between five minutes and seven days",
        )
    appointment_link = None
    if communication_purpose == "appointment_invitation":
        appointment_link = _appointment_link(version.content)
        if not confirm_appointment_details:
            _deny(
                "appointment_details_attestation_required",
                "Appointment date, time, location, and link require explicit confirmation",
            )
    terminology = assess_medication_terminology(version.content)
    if not terminology["release_permitted_after_confirmation"]:
        _deny(
            "terminology_release_blocked",
            "Medication or dose evidence is unresolved; revise the copy before delivery",
        )
    if terminology["human_confirmation_required"] and not confirm_medication_and_dose:
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
            or existing.approval_evidence.get("communication_purpose", "care_summary")
            != communication_purpose
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
        original_purpose = correction_for.approval_evidence.get(
            "communication_purpose", "care_summary"
        )
        if communication_purpose != original_purpose:
            _deny(
                "correction_purpose_mismatch",
                "A correction must retain the original communication purpose",
            )
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
            "dose_sensitive": terminology["dose_sensitive"],
            "terminology": terminology,
            "communication_purpose": communication_purpose,
            "appointment_details": confirm_appointment_details,
            "appointment_link_hash": (
                None if appointment_link is None else sha256(appointment_link.encode()).hexdigest()
            ),
            "acknowledgement_window_minutes": acknowledgement_window_minutes,
        },
        approved_by=actor.id,
    )
    session.add(delivery)
    session.flush()
    if appointment_link is not None:
        session.add(
            DeliveryFollowUp(
                clinic_id=actor.clinic_id,
                patient_id=patient.id,
                delivery_id=delivery.id,
                purpose="appointment_invitation",
                acknowledgement_window_minutes=acknowledgement_window_minutes,
                appointment_link_hash=sha256(appointment_link.encode()).hexdigest(),
            )
        )
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
            "terminology_status": terminology["status"],
            "communication_purpose": communication_purpose,
            "acknowledgement_window_minutes": acknowledgement_window_minutes,
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
    timestamp = _as_utc(occurred_at or datetime.now(UTC))
    follow_up = session.scalar(
        select(DeliveryFollowUp).where(DeliveryFollowUp.delivery_id == delivery.id)
    )
    delivery.status = outcome
    delivery.updated_at = timestamp
    if outcome in {"accepted", "failed"}:
        delivery.attempt_count += 1
    if outcome == "accepted":
        delivery.provider_message_id = _safe_provider_id(provider_message_id or "")
        delivery.failure_code = None
        delivery.accepted_at = timestamp
        if follow_up is not None:
            follow_up.status = "pending_delivery"
            follow_up.updated_at = timestamp
    elif outcome == "delivered":
        delivery.delivered_at = timestamp
        if follow_up is not None:
            follow_up.status = "awaiting_patient_acknowledgement"
            follow_up.acknowledge_by = timestamp + timedelta(
                minutes=follow_up.acknowledgement_window_minutes
            )
            follow_up.updated_at = timestamp
        if delivery.correction_for_id is not None:
            original = session.get(OutboundDelivery, delivery.correction_for_id)
            if original is None or original.clinic_id != actor.clinic_id:
                _deny("correction_original_missing", "The original delivery cannot be resolved")
            original.status = "superseded"
            original.superseded_at = timestamp
            original.updated_at = timestamp
            original_follow_up = session.scalar(
                select(DeliveryFollowUp).where(
                    DeliveryFollowUp.delivery_id == delivery.correction_for_id
                )
            )
            if original_follow_up is not None:
                original_follow_up.status = "superseded"
                original_follow_up.updated_at = timestamp
                if original_follow_up.escalation_task_id is not None:
                    original_task = session.get(CareTask, original_follow_up.escalation_task_id)
                    original_task.status = "completed"
    elif outcome == "failed":
        delivery.failure_code = failure_code
        if follow_up is not None:
            follow_up.status = "delivery_failed"
            follow_up.updated_at = timestamp
    else:
        delivery.failure_code = None
        if follow_up is not None:
            follow_up.status = "pending_provider_acceptance"
            follow_up.updated_at = timestamp

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


def acknowledge_appointment_delivery(
    session: Session,
    *,
    actor: User,
    delivery: OutboundDelivery,
    occurred_at: datetime | None = None,
) -> DeliveryFollowUp:
    """Record a patient-authenticated acknowledgement, distinct from provider delivery."""

    if actor.role != "patient":
        _deny(
            "patient_acknowledgement_required",
            "Only the patient can acknowledge this invitation",
        )
    if delivery.clinic_id != actor.clinic_id or delivery.patient_id != actor.patient_id:
        _deny("delivery_acknowledgement_scope_mismatch", "The delivery belongs to another patient")
    follow_up = session.scalar(
        select(DeliveryFollowUp).where(DeliveryFollowUp.delivery_id == delivery.id)
    )
    if follow_up is None:
        _deny("appointment_follow_up_missing", "This delivery is not an appointment invitation")
    if follow_up.status in {"acknowledged", "acknowledged_after_escalation"}:
        return follow_up
    if delivery.status != "delivered" or follow_up.status not in {
        "awaiting_patient_acknowledgement",
        "escalated",
    }:
        _deny(
            "appointment_acknowledgement_not_ready",
            "The invitation cannot be acknowledged before confirmed provider delivery",
        )

    timestamp = _as_utc(occurred_at or datetime.now(UTC))
    late = follow_up.escalated_at is not None
    follow_up.status = "acknowledged_after_escalation" if late else "acknowledged"
    follow_up.acknowledged_at = timestamp
    follow_up.updated_at = timestamp
    if follow_up.escalation_task_id is not None:
        task = session.get(CareTask, follow_up.escalation_task_id)
        task.status = "completed"
    append_audit(
        session,
        clinic_id=actor.clinic_id,
        actor_id=actor.id,
        action="delivery.patient_acknowledged",
        object_type="delivery_follow_up",
        object_id=follow_up.id,
        metadata={
            "communication_purpose": follow_up.purpose,
            "follow_up_status": follow_up.status,
        },
    )
    return follow_up


def escalate_appointment_followups(
    session: Session,
    *,
    actor: User,
    patient: Patient,
    as_of: datetime | None = None,
) -> list[DeliveryFollowUp]:
    """Escalate failed or overdue appointment invitations to an owned care task."""

    if actor.role not in {"staff", "clinician", "admin"}:
        _deny("follow_up_control_required", "Only the care team can run follow-up escalation")
    if patient.clinic_id != actor.clinic_id:
        _deny("delivery_tenant_mismatch", "The patient belongs to another clinic")
    timestamp = _as_utc(as_of or datetime.now(UTC))
    owner_id = _follow_up_owner_id(session, actor)
    candidates = list(
        session.scalars(
            select(DeliveryFollowUp)
            .where(
                DeliveryFollowUp.patient_id == patient.id,
                DeliveryFollowUp.status.in_(
                    ["delivery_failed", "awaiting_patient_acknowledgement"]
                ),
            )
            .with_for_update(skip_locked=True)
        )
    )
    escalated: list[DeliveryFollowUp] = []
    for follow_up in candidates:
        is_overdue = (
            follow_up.status == "awaiting_patient_acknowledgement"
            and follow_up.acknowledge_by is not None
            and _as_utc(follow_up.acknowledge_by) <= timestamp
        )
        if follow_up.status != "delivery_failed" and not is_overdue:
            continue
        delivery = session.get(OutboundDelivery, follow_up.delivery_id)
        task = CareTask(
            clinic_id=actor.clinic_id,
            patient_id=patient.id,
            source_entry_id=delivery.source_entry_id,
            title="Contact patient: appointment invitation not acknowledged",
            status="open",
            urgency="high",
            assigned_to=owner_id,
            due_at=timestamp,
            created_by=actor.id,
        )
        session.add(task)
        session.flush()
        follow_up.status = "escalated"
        follow_up.escalated_at = timestamp
        follow_up.escalation_task_id = task.id
        follow_up.updated_at = timestamp
        append_audit(
            session,
            clinic_id=actor.clinic_id,
            actor_id=actor.id,
            action="delivery.follow_up_escalated",
            object_type="delivery_follow_up",
            object_id=follow_up.id,
            metadata={
                "communication_purpose": follow_up.purpose,
                "follow_up_status": follow_up.status,
            },
        )
        escalated.append(follow_up)
    return escalated


def delivery_snapshot(
    session: Session,
    patient: Patient,
    *,
    include_internal: bool = True,
) -> dict:
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
    follow_ups = {
        item.delivery_id: item
        for item in session.scalars(
            select(DeliveryFollowUp).where(DeliveryFollowUp.patient_id == patient.id)
        )
    }
    patient_facing_entries = (
        list(
            session.scalars(
                select(Entry).where(
                    Entry.patient_id == patient.id,
                    Entry.visibility == "patient",
                    Entry.owner_role == "clinician",
                    Entry.trust_state == "clinician_confirmed",
                    Entry.entry_type.in_(["patient_summary", "patient_instruction"]),
                )
            )
        )
        if include_internal
        else []
    )
    current_versions = {
        entry.id: entry.current_version_id
        for entry in session.scalars(
            select(Entry).where(Entry.id.in_({item.source_entry_id for item in deliveries}))
        )
    }
    terminology_assessments = []
    for entry in patient_facing_entries:
        version = current_version(session, entry)
        terminology_assessments.append(
            {
                "entry_id": entry.id,
                "source_version_id": version.id,
                "current_version": entry.current_version,
                **assess_medication_terminology(version.content),
            }
        )
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
                "patient_id": item.patient_id,
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
                "communication_purpose": item.approval_evidence.get(
                    "communication_purpose", "care_summary"
                ),
                "follow_up": (
                    None
                    if (follow_up := follow_ups.get(item.id)) is None
                    else {
                        "id": follow_up.id,
                        "purpose": follow_up.purpose,
                        "status": follow_up.status,
                        "acknowledgement_window_minutes": (
                            follow_up.acknowledgement_window_minutes
                        ),
                        "acknowledge_by": (
                            None
                            if follow_up.acknowledge_by is None
                            else follow_up.acknowledge_by.isoformat()
                        ),
                        "acknowledged_at": (
                            None
                            if follow_up.acknowledged_at is None
                            else follow_up.acknowledged_at.isoformat()
                        ),
                        "escalated_at": (
                            None
                            if follow_up.escalated_at is None
                            else follow_up.escalated_at.isoformat()
                        ),
                        "requires_patient_acknowledgement": True,
                    }
                ),
                "attempt_count": item.attempt_count,
                "created_at": item.created_at.isoformat(),
                "accepted_at": None if item.accepted_at is None else item.accepted_at.isoformat(),
                "delivered_at": (
                    None if item.delivered_at is None else item.delivered_at.isoformat()
                ),
                "superseded_at": (
                    None if item.superseded_at is None else item.superseded_at.isoformat()
                ),
                **(
                    {
                        "failure_code": item.failure_code,
                        "approved_by": item.approved_by,
                        "approval_evidence": item.approval_evidence,
                    }
                    if include_internal
                    else {}
                ),
            }
            for item in deliveries
        ],
        **({"terminology_assessments": terminology_assessments} if include_internal else {}),
        "safety_contract": (
            "Provider acceptance, provider delivery, and patient acknowledgement are distinct "
            "facts. Sent snapshots remain immutable; corrections preserve the original side by "
            "side, and failed or overdue appointment invitations escalate to an owned care task."
        ),
    }
