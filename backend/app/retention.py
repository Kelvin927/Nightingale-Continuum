"""Tier derived data while preserving source, audit, and active safety evidence."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import append_audit
from .care import current_version
from .constants import NON_DECAY_ENTITY_TAGS
from .models import (
    CareTask,
    Entry,
    Highlight,
    ProvenanceSpan,
    RetentionManifest,
    User,
)


def recommended_tier(
    session: Session, entry: Entry, now: datetime | None = None
) -> tuple[str, str]:
    reference_time = now or datetime.now(UTC)
    created = (
        entry.created_at.replace(tzinfo=UTC)
        if entry.created_at.tzinfo is None
        else entry.created_at
    )
    age_days = (reference_time - created).days
    active_task = session.scalar(
        select(CareTask.id).where(
            CareTask.source_entry_id == entry.id,
            CareTask.status == "open",
        )
    )
    safety_highlight = session.scalar(
        select(Highlight)
        .join(ProvenanceSpan, Highlight.provenance_span_id == ProvenanceSpan.id)
        .where(
            ProvenanceSpan.source_entry_id == entry.id,
            Highlight.status.in_(["suggested", "accepted", "pinned"]),
        )
    )
    if active_task is not None:
        return "hot", "Open task protects the source from decay"
    if safety_highlight is not None and NON_DECAY_ENTITY_TAGS & set(safety_highlight.entity_tags):
        return "hot", "Active safety evidence protects the source from decay"
    if safety_highlight is not None and safety_highlight.status == "pinned":
        return "hot", "Clinician or staff pin protects the source from decay"
    if age_days >= 365:
        return "cold", "Older resolved source; immutable version remains addressable"
    if age_days >= 90:
        return "warm", "Older context; derived caches may be recomputed on demand"
    return "hot", "Recent longitudinal context"


def apply_retention_policy(
    session: Session,
    *,
    actor: User,
    now: datetime | None = None,
) -> list[RetentionManifest]:
    manifests: list[RetentionManifest] = []
    entries = list(session.scalars(select(Entry).where(Entry.clinic_id == actor.clinic_id)))
    for entry in entries:
        target, reason = recommended_tier(session, entry, now)
        if target == entry.retention_tier:
            continue
        version = current_version(session, entry)
        manifest = RetentionManifest(
            clinic_id=entry.clinic_id,
            entry_id=entry.id,
            from_tier=entry.retention_tier,
            to_tier=target,
            reason=reason,
            source_hash=version.content_hash,
            dropped_derivatives=[] if target == "hot" else ["ranking_cache", "embedding_cache"],
            created_by=actor.id,
        )
        session.add(manifest)
        entry.retention_tier = target
        session.flush()
        append_audit(
            session,
            clinic_id=actor.clinic_id,
            actor_id=actor.id,
            action="retention.tier_changed",
            object_type="entry",
            object_id=entry.id,
            object_version=entry.current_version,
            metadata={"from_tier": manifest.from_tier, "to_tier": target},
        )
        manifests.append(manifest)
    return manifests
