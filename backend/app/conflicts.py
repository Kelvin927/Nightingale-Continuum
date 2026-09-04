"""Detect a deliberately bounded set of high-severity record contradictions."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import append_audit
from .care import current_version
from .models import Conflict, Entry, EntryVersion, User

MEDICATION_NAMES = ("lisinopril", "metformin", "amlodipine", "warfarin", "insulin")
ALLERGY_SUBSTANCES = ("penicillin", "lisinopril", "metformin", "latex")
DOSE_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mcg|mg|g|ml|units?)\b", re.IGNORECASE)
NO_ALLERGY_PATTERN = re.compile(
    r"\b(?:no known (?:drug )?allerg(?:y|ies)|nkda|no (?:documented )?allerg(?:y|ies))\b",
    re.IGNORECASE,
)


class ConflictResolutionError(ValueError):
    """Represent a stable failure in the human conflict-resolution workflow."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _medication_doses(content: str) -> dict[str, set[str]]:
    """Extract dose strings only for the explicitly supported medication vocabulary."""

    lowered = content.casefold()
    doses: defaultdict[str, set[str]] = defaultdict(set)
    for medication in MEDICATION_NAMES:
        pattern = re.compile(rf"\b{re.escape(medication)}\b(?P<clause>[^.!?\n]*)")
        for match in pattern.finditer(lowered):
            clause = match.group("clause")
            for dose in DOSE_PATTERN.findall(clause):
                doses[medication].add(re.sub(r"\s+", " ", dose.casefold()).strip())
    return dict(doses)


def _allergy_assertions(content: str) -> tuple[set[str], bool]:
    """Return supported positive substances and a global negative-allergy assertion."""

    lowered = content.casefold()
    positive: set[str] = set()
    for sentence in re.split(r"[.!?\n]+", lowered):
        if NO_ALLERGY_PATTERN.search(sentence):
            continue
        has_reaction = any(
            term in sentence for term in ("allerg", "anaphyl", "facial swelling", "rash")
        )
        if not has_reaction:
            continue
        positive.update(substance for substance in ALLERGY_SUBSTANCES if substance in sentence)
    return positive, bool(NO_ALLERGY_PATTERN.search(lowered))


def _already_open(
    session: Session,
    *,
    patient_id: str,
    conflict_type: str,
    summary: str,
    left_version_id: str,
    right_version_id: str,
) -> bool:
    pair = {left_version_id, right_version_id}
    return any(
        {item.left_version_id, item.right_version_id} == pair
        for item in session.scalars(
            select(Conflict).where(
                Conflict.patient_id == patient_id,
                Conflict.conflict_type == conflict_type,
                Conflict.summary == summary,
                Conflict.status == "open",
            )
        )
    )


def detect_structured_conflicts(session: Session, entry: Entry) -> list[Conflict]:
    """Create review records for current-version dose and allergy contradictions.

    This is intentionally not a general clinical NLP claim. Unsupported drugs,
    negation patterns, temporal interpretation, and clinical resolution remain a
    human-review boundary.
    """

    version = current_version(session, entry)
    doses = _medication_doses(version.content)
    allergies, denies_allergies = _allergy_assertions(version.content)
    created: list[Conflict] = []
    others = session.scalars(
        select(Entry).where(
            Entry.clinic_id == entry.clinic_id,
            Entry.patient_id == entry.patient_id,
        )
    )
    for other in others:
        other_version = current_version(session, other)
        other_doses = _medication_doses(other_version.content)
        other_allergies, other_denies_allergies = _allergy_assertions(other_version.content)

        for medication in sorted(doses.keys() & other_doses.keys()):
            if doses[medication] == other_doses[medication]:
                continue
            conflict_type = "medication_dose_mismatch"
            summary = (
                f"Dose mismatch for {medication}: "
                f"{', '.join(sorted(doses[medication]))} versus "
                f"{', '.join(sorted(other_doses[medication]))}."
            )
            if _already_open(
                session,
                patient_id=entry.patient_id,
                conflict_type=conflict_type,
                summary=summary,
                left_version_id=version.id,
                right_version_id=other_version.id,
            ):
                continue
            conflict = Conflict(
                clinic_id=entry.clinic_id,
                patient_id=entry.patient_id,
                left_version_id=version.id,
                right_version_id=other_version.id,
                conflict_type=conflict_type,
                summary=summary,
            )
            session.add(conflict)
            session.flush()
            created.append(conflict)

        allergy_mismatch = (denies_allergies and other_allergies) or (
            other_denies_allergies and allergies
        )
        if not allergy_mismatch:
            continue
        conflict_type = "allergy_status_mismatch"
        substances = sorted(allergies | other_allergies)
        summary = (
            "Allergy status mismatch: a no-known-allergy statement conflicts with "
            f"a recorded reaction to {', '.join(substances)}."
        )
        if _already_open(
            session,
            patient_id=entry.patient_id,
            conflict_type=conflict_type,
            summary=summary,
            left_version_id=version.id,
            right_version_id=other_version.id,
        ):
            continue
        conflict = Conflict(
            clinic_id=entry.clinic_id,
            patient_id=entry.patient_id,
            left_version_id=version.id,
            right_version_id=other_version.id,
            conflict_type=conflict_type,
            summary=summary,
        )
        session.add(conflict)
        session.flush()
        created.append(conflict)
    return created


def resolve_conflict(
    session: Session,
    *,
    actor: User,
    conflict: Conflict,
    decision: str,
    rationale: str,
    confirm_sources_reviewed: bool,
) -> Conflict:
    """Record a clinician decision without deleting or rewriting either assertion."""

    if conflict.clinic_id != actor.clinic_id:
        raise ConflictResolutionError("conflict_scope_mismatch", "Conflict is outside clinic")
    if actor.role != "clinician":
        raise ConflictResolutionError(
            "clinician_conflict_review_required",
            "Only a clinician can resolve a clinical contradiction",
        )
    if conflict.status != "open":
        raise ConflictResolutionError(
            "conflict_not_open",
            "Only an open conflict can receive a decision",
        )
    if decision not in {"confirm_left", "confirm_right", "escalate_unresolved"}:
        raise ConflictResolutionError("invalid_conflict_decision", "Unknown conflict decision")
    if not confirm_sources_reviewed:
        raise ConflictResolutionError(
            "source_review_attestation_required",
            "Both immutable source versions must be reviewed",
        )
    conflict.status = "escalated" if decision == "escalate_unresolved" else "resolved"
    conflict.disposition = f"{decision}|{rationale}"
    conflict.resolved_by = actor.id
    append_audit(
        session,
        clinic_id=conflict.clinic_id,
        actor_id=actor.id,
        action="conflict.reviewed",
        object_type="conflict",
        object_id=conflict.id,
        metadata={
            "conflict_decision": decision,
            "sources_reviewed": confirm_sources_reviewed,
        },
    )
    return conflict


def _source_evidence(session: Session, conflict: Conflict, version_id: str) -> dict:
    version = session.get(EntryVersion, version_id)
    if version is None:
        return {"state": "unavailable", "version_id": version_id}
    entry = session.get(Entry, version.entry_id)
    if entry is None or entry.clinic_id != conflict.clinic_id:
        return {"state": "unavailable", "version_id": version_id}
    author = session.get(User, entry.author_id) if entry.author_id else None
    return {
        "state": "available",
        "entry_id": entry.id,
        "entry_title": entry.title,
        "entry_type": entry.entry_type,
        "owner_role": entry.owner_role,
        "trust_state": entry.trust_state,
        "author": (
            None
            if author is None
            else {
                "id": author.id,
                "display_name": author.display_name,
                "role": author.role,
            }
        ),
        "version_id": version.id,
        "version": version.version,
        "content": version.content,
        "content_hash": version.content_hash,
        "source_is_current": entry.current_version_id == version.id,
        "created_at": version.created_at.isoformat(),
    }


def serialize_conflict(session: Session, conflict: Conflict) -> dict:
    decision = None
    rationale = None
    if conflict.disposition:
        decision_value, separator, rationale_value = conflict.disposition.partition("|")
        if separator:
            decision = decision_value
            rationale = rationale_value
        else:
            rationale = conflict.disposition
    return {
        "id": conflict.id,
        "conflict_type": conflict.conflict_type,
        "summary": conflict.summary,
        "status": conflict.status,
        "disposition": conflict.disposition,
        "resolution": {
            "decision": decision,
            "rationale": rationale,
            "resolved_by": conflict.resolved_by,
        },
        "left": _source_evidence(session, conflict, conflict.left_version_id),
        "right": _source_evidence(session, conflict, conflict.right_version_id),
        "decision_policy": (
            "No automatic winner: preserve both immutable assertions and require clinician "
            "source review or explicit escalation."
        ),
        "created_at": (
            conflict.created_at.replace(tzinfo=UTC).isoformat()
            if conflict.created_at.tzinfo is None
            else conflict.created_at.isoformat()
        ),
    }
