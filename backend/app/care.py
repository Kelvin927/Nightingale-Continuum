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
    base_snapshot: dict[str, object] | None = None
    current_snapshot: dict[str, object] | None = None
    proposed_content: str | None = None
    proposed_content_hash: str | None = None
    merge_assistance: dict[str, object] | None = None


def _line_edits(base: str, changed: str) -> list[tuple[int, int, list[str]]]:
    base_lines = base.splitlines(keepends=True)
    changed_lines = changed.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=base_lines, b=changed_lines)
    return [
        (start, end, changed_lines[changed_start:changed_end])
        for operation, start, end, changed_start, changed_end in matcher.get_opcodes()
        if operation != "equal"
    ]


def _edits_overlap(
    left: tuple[int, int, list[str]],
    right: tuple[int, int, list[str]],
) -> bool:
    left_start, left_end, _ = left
    right_start, right_end, _ = right
    if left_start == left_end and right_start == right_end:
        return left_start == right_start
    if left_start == left_end:
        return right_start <= left_start <= right_end
    if right_start == right_end:
        return left_start <= right_start <= left_end
    return max(left_start, right_start) < min(left_end, right_end)


def build_merge_assistance(base: str, proposed: str, current: str) -> dict[str, object]:
    """Build a conservative three-way draft; never persist it automatically."""

    if proposed == current:
        return {
            "status": "identical",
            "auto_merge_safe": True,
            "merged_content": current,
            "conflicting_hunks": [],
        }
    if proposed == base:
        return {
            "status": "current_only",
            "auto_merge_safe": True,
            "merged_content": current,
            "conflicting_hunks": [],
        }
    if current == base:
        return {
            "status": "proposed_only",
            "auto_merge_safe": True,
            "merged_content": proposed,
            "conflicting_hunks": [],
        }

    proposed_edits = _line_edits(base, proposed)
    current_edits = _line_edits(base, current)
    overlaps = [
        {
            "base_start_line": max(left[0], right[0]) + 1,
            "base_end_line": max(left[1], right[1]),
            "proposed_text": "".join(left[2]),
            "current_text": "".join(right[2]),
        }
        for left in proposed_edits
        for right in current_edits
        if _edits_overlap(left, right)
    ]
    if overlaps:
        return {
            "status": "manual_review_required",
            "auto_merge_safe": False,
            "merged_content": None,
            "conflicting_hunks": overlaps,
        }

    merged_lines = base.splitlines(keepends=True)
    for start, end, replacement in sorted(
        [*proposed_edits, *current_edits], key=lambda edit: (edit[0], edit[1]), reverse=True
    ):
        merged_lines[start:end] = replacement
    return {
        "status": "non_overlapping_draft",
        "auto_merge_safe": True,
        "merged_content": "".join(merged_lines),
        "conflicting_hunks": [],
    }


def _version_snapshot(version: EntryVersion) -> dict[str, object]:
    return {
        "version_id": version.id,
        "version": version.version,
        "content": version.content,
        "content_hash": version.content_hash,
        "created_at": version.created_at.isoformat(),
    }


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
        base = session.scalar(
            select(EntryVersion).where(
                EntryVersion.entry_id == entry.id,
                EntryVersion.version == expected_version,
            )
        )
        latest = current_version(session, entry) if entry.current_version_id else None
        raise VersionConflictError(
            expected_version,
            entry.current_version,
            entry.current_version_id or "",
            base_snapshot=_version_snapshot(base) if base else None,
            current_snapshot=_version_snapshot(latest) if latest else None,
            proposed_content=content,
            proposed_content_hash=content_hash(content),
            merge_assistance=(
                build_merge_assistance(base.content, content, latest.content)
                if base and latest
                else None
            ),
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
