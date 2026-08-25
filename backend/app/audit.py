from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AuditEvent, new_id

GENESIS_HASH = "0" * 64
FORBIDDEN_METADATA_KEYS = {
    "body",
    "content",
    "note",
    "prompt",
    "quote",
    "raw",
    "redacted_value",
    "transcript",
}


def _canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _validate_metadata(value: dict) -> None:
    keys = {str(key).lower() for key in value}
    blocked = keys & FORBIDDEN_METADATA_KEYS
    if blocked:
        raise ValueError(f"Audit metadata contains forbidden keys: {sorted(blocked)}")


def append_audit(
    session: Session,
    *,
    clinic_id: str,
    actor_id: str | None,
    action: str,
    object_type: str,
    object_id: str,
    object_version: int | None = None,
    request_id: str | None = None,
    metadata: dict | None = None,
    created_at: datetime | None = None,
) -> AuditEvent:
    safe_metadata = metadata or {}
    _validate_metadata(safe_metadata)

    previous = session.scalar(
        select(AuditEvent)
        .where(AuditEvent.clinic_id == clinic_id)
        .order_by(AuditEvent.sequence.desc())
        .limit(1)
    )
    sequence = 1 if previous is None else previous.sequence + 1
    previous_hash = GENESIS_HASH if previous is None else previous.event_hash
    timestamp = created_at or datetime.now(UTC)
    event_id = new_id()
    payload = {
        "id": event_id,
        "clinic_id": clinic_id,
        "sequence": sequence,
        "actor_id": actor_id,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "object_version": object_version,
        "request_id": request_id or new_id(),
        "metadata": safe_metadata,
        "previous_hash": previous_hash,
        "created_at": timestamp.isoformat(),
    }
    event_hash = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
    event = AuditEvent(
        id=event_id,
        clinic_id=clinic_id,
        sequence=sequence,
        actor_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        object_version=object_version,
        request_id=payload["request_id"],
        event_metadata=safe_metadata,
        previous_hash=previous_hash,
        event_hash=event_hash,
        created_at=timestamp,
    )
    session.add(event)
    session.flush()
    return event


@dataclass(frozen=True)
class AuditVerification:
    valid: bool
    events_checked: int
    first_invalid_sequence: int | None = None
    reason: str | None = None


def verify_audit_chain(session: Session, clinic_id: str) -> AuditVerification:
    events = list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.clinic_id == clinic_id)
            .order_by(AuditEvent.sequence)
        )
    )
    expected_previous = GENESIS_HASH
    expected_sequence = 1
    for event in events:
        if event.sequence != expected_sequence:
            return AuditVerification(False, expected_sequence - 1, event.sequence, "sequence gap")
        if event.previous_hash != expected_previous:
            return AuditVerification(False, expected_sequence - 1, event.sequence, "previous hash")
        payload = {
            "id": event.id,
            "clinic_id": event.clinic_id,
            "sequence": event.sequence,
            "actor_id": event.actor_id,
            "action": event.action,
            "object_type": event.object_type,
            "object_id": event.object_id,
            "object_version": event.object_version,
            "request_id": event.request_id,
            "metadata": event.event_metadata,
            "previous_hash": event.previous_hash,
            "created_at": event.created_at.replace(tzinfo=UTC).isoformat()
            if event.created_at.tzinfo is None
            else event.created_at.isoformat(),
        }
        actual_hash = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
        if actual_hash != event.event_hash:
            return AuditVerification(False, expected_sequence - 1, event.sequence, "event hash")
        expected_previous = event.event_hash
        expected_sequence += 1
    return AuditVerification(True, len(events))


def audit_count(session: Session, clinic_id: str) -> int:
    return int(
        session.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.clinic_id == clinic_id))
        or 0
    )
