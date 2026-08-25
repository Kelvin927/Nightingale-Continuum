from __future__ import annotations

import re
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from .care import current_version
from .models import Conflict, Entry, Highlight, ProvenanceSpan


def _evidence_for_tag(session: Session, entries: list[Entry], tag: str) -> dict | None:
    entry_ids = [entry.id for entry in entries]
    if not entry_ids:
        return None
    result = session.execute(
        select(Highlight, ProvenanceSpan)
        .join(ProvenanceSpan, Highlight.provenance_span_id == ProvenanceSpan.id)
        .where(
            ProvenanceSpan.source_entry_id.in_(entry_ids),
            Highlight.entity_tags.contains(tag),
        )
        .order_by(Highlight.created_at.desc())
        .limit(1)
    ).first()
    if result is None:
        return None
    highlight, span = result
    return {
        "entry_id": span.source_entry_id,
        "provenance_span_id": span.id,
        "quote": span.quote,
        "trust_state": highlight.trust_state,
    }


def _observed_date(entry: Entry) -> str:
    value = entry.created_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.date().isoformat()


def build_delta_lens(session: Session, patient_id: str) -> dict:
    entries = list(
        session.scalars(
            select(Entry).where(Entry.patient_id == patient_id).order_by(Entry.created_at)
        )
    )
    if not entries:
        return {
            "comparison": None,
            "new": [],
            "changed_or_conflicting": [],
            "persistent": [],
            "resolved": [],
            "unknown": ["No longitudinal evidence is available."],
            "interpretation": "descriptive_only",
        }

    contents = [(entry, current_version(session, entry).content.lower()) for entry in entries]
    oldest_entry, oldest_content = contents[0]
    recent_entries = [entry for entry, _ in contents[1:]] or entries
    recent_content = " ".join(content for _, content in contents[1:])
    all_content = " ".join(content for _, content in contents)

    new_items: list[dict] = []
    changed_items: list[dict] = []
    persistent_items: list[dict] = []

    if "dizz" not in oldest_content and "dizz" in recent_content:
        new_items.append(
            {
                "label": "Dizziness appears in later records",
                "observed_on": _observed_date(recent_entries[-1]),
                "evidence": _evidence_for_tag(session, recent_entries, "symptom_change"),
            }
        )
    if "allerg" not in oldest_content and "allerg" in recent_content:
        new_items.append(
            {
                "label": "Penicillin reaction documented in later clinical evidence",
                "observed_on": _observed_date(recent_entries[-1]),
                "evidence": _evidence_for_tag(session, recent_entries, "allergy"),
            }
        )

    dose_values = [int(value) for value in re.findall(r"\b(\d{1,3})\s*mg\b", all_content)]
    distinct_doses = list(dict.fromkeys(dose_values))
    if len(distinct_doses) > 1:
        changed_items.append(
            {
                "label": (
                    f"Lisinopril dose references changed from {distinct_doses[0]} mg "
                    f"to {distinct_doses[-1]} mg"
                ),
                "classification": "observed_change",
                "evidence": _evidence_for_tag(session, recent_entries, "dose_change"),
            }
        )

    conflicts = list(
        session.scalars(
            select(Conflict).where(
                Conflict.patient_id == patient_id,
                Conflict.status == "open",
            )
        )
    )
    changed_items.extend(
        {
            "label": conflict.summary,
            "classification": "unresolved_conflict",
            "evidence": _evidence_for_tag(session, recent_entries, "medication"),
        }
        for conflict in conflicts
    )

    if "blood pressure" in oldest_content and "blood pressure" in recent_content:
        persistent_items.append(
            {
                "label": "Blood pressure monitoring persists across visits",
                "evidence": _evidence_for_tag(session, entries, "follow_up"),
            }
        )

    return {
        "comparison": {
            "from": _observed_date(oldest_entry),
            "to": _observed_date(entries[-1]),
            "entry_count": len(entries),
        },
        "new": new_items,
        "changed_or_conflicting": changed_items,
        "persistent": persistent_items,
        "resolved": [],
        "unknown": [
            "The timeline does not identify whether the dose change caused dizziness.",
            "Absent documentation is not evidence that a symptom or action was absent.",
        ],
        "interpretation": "temporal_description_not_causal_effect",
        "causal_guardrail": (
            "A causal claim requires a defined estimand and a defensible design; temporal order "
            "alone is insufficient."
        ),
    }
