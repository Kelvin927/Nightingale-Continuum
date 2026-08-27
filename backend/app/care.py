"""Manage immutable care-note versions, threads, and actor-safe projections."""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import append_audit
from .models import Entry, EntryVersion, User


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


@dataclass(frozen=True)
class VersionConflictError(Exception):
    expected_version: int
    current_version: int
    current_version_id: str


def current_version(session: Session, entry: Entry) -> EntryVersion:
    if entry.current_version_id is None:
        raise RuntimeError(f"Entry {entry.id} has no current version")
    version = session.get(EntryVersion, entry.current_version_id)
    if version is None:
        raise RuntimeError(f"Entry {entry.id} points to a missing version")
    return version


def create_entry(
    session: Session,
    *,
    actor: User | None,
    clinic_id: str,
    patient_id: str,
    owner_role: str,
    entry_type: str,
    title: str,
    content: str,
    visibility: str,
    trust_state: str,
    source_uri: str | None = None,
    created_at: datetime | None = None,
    change_reason: str = "Initial version",
    request_id: str | None = None,
) -> Entry:
    timestamp = created_at or datetime.now(UTC)
    entry = Entry(
        clinic_id=clinic_id,
        patient_id=patient_id,
        author_id=actor.id if actor else None,
        owner_role=owner_role,
        entry_type=entry_type,
        title=title,
        visibility=visibility,
        trust_state=trust_state,
        source_uri=source_uri,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(entry)
    session.flush()
    version = EntryVersion(
        entry_id=entry.id,
        version=1,
        content=content,
        content_hash=content_hash(content),
        created_by=actor.id if actor else None,
        change_reason=change_reason,
        created_at=timestamp,
    )
    session.add(version)
    session.flush()
    entry.current_version_id = version.id
    entry.current_version = 1
    append_audit(
        session,
        clinic_id=clinic_id,
        actor_id=actor.id if actor else None,
        action="entry.created",
        object_type="entry",
        object_id=entry.id,
        object_version=1,
        request_id=request_id,
        metadata={"entry_type": entry_type, "owner_role": owner_role, "visibility": visibility},
        created_at=timestamp,
    )
    return entry


def edit_entry(
    session: Session,
    *,
    actor: User,
    entry: Entry,
    content: str,
    expected_version: int,
    reason: str,
    request_id: str | None = None,
) -> EntryVersion:
    if expected_version != entry.current_version:
        raise VersionConflictError(
            expected_version,
            entry.current_version,
            entry.current_version_id or "",
        )
    prior = current_version(session, entry)
    next_version = EntryVersion(
        entry_id=entry.id,
        version=entry.current_version + 1,
        content=content,
        content_hash=content_hash(content),
        created_by=actor.id,
        change_reason=reason,
    )
    session.add(next_version)
    session.flush()
    entry.current_version_id = next_version.id
    entry.current_version = next_version.version
    entry.updated_at = datetime.now(UTC)
    append_audit(
        session,
        clinic_id=entry.clinic_id,
        actor_id=actor.id,
        action="entry.edited",
        object_type="entry",
        object_id=entry.id,
        object_version=next_version.version,
        request_id=request_id,
        metadata={"from_version": prior.version, "to_version": next_version.version},
    )
    return next_version


def revert_entry(
    session: Session,
    *,
    actor: User,
    entry: Entry,
    target_version: int,
    expected_version: int,
    reason: str,
    request_id: str | None = None,
) -> EntryVersion:
    if expected_version != entry.current_version:
        raise VersionConflictError(
            expected_version,
            entry.current_version,
            entry.current_version_id or "",
        )
    target = session.scalar(
        select(EntryVersion).where(
            EntryVersion.entry_id == entry.id,
            EntryVersion.version == target_version,
        )
    )
    if target is None:
        raise ValueError("Target version does not exist")
    new_version = EntryVersion(
        entry_id=entry.id,
        version=entry.current_version + 1,
        content=target.content,
        content_hash=target.content_hash,
        created_by=actor.id,
        change_reason=reason,
        reverted_from_version_id=target.id,
    )
    session.add(new_version)
    session.flush()
    prior_version = entry.current_version
    entry.current_version = new_version.version
    entry.current_version_id = new_version.id
    entry.updated_at = datetime.now(UTC)
    append_audit(
        session,
        clinic_id=entry.clinic_id,
        actor_id=actor.id,
        action="entry.reverted",
        object_type="entry",
        object_id=entry.id,
        object_version=new_version.version,
        request_id=request_id,
        metadata={
            "from_version": prior_version,
            "target_version": target_version,
            "to_version": new_version.version,
        },
    )
    return new_version


def version_diff(older: EntryVersion, newer: EntryVersion) -> list[dict[str, str]]:
    matcher = difflib.SequenceMatcher(a=older.content.splitlines(), b=newer.content.splitlines())
    changes: list[dict[str, str]] = []
    for operation, i1, i2, j1, j2 in matcher.get_opcodes():
        if operation == "equal":
            continue
        changes.append(
            {
                "operation": operation,
                "before": "\n".join(older.content.splitlines()[i1:i2]),
                "after": "\n".join(newer.content.splitlines()[j1:j2]),
            }
        )
    return changes
