"""Detect a deliberately bounded set of high-severity record contradictions."""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .care import current_version
from .models import Conflict, Entry

MEDICATION_NAMES = ("lisinopril", "metformin", "amlodipine", "warfarin", "insulin")
ALLERGY_SUBSTANCES = ("penicillin", "lisinopril", "metformin", "latex")
DOSE_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mcg|mg|g|ml|units?)\b", re.IGNORECASE)
NO_ALLERGY_PATTERN = re.compile(
    r"\b(?:no known (?:drug )?allerg(?:y|ies)|nkda|no (?:documented )?allerg(?:y|ies))\b",
    re.IGNORECASE,
)


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
    positive = {
        substance
        for substance in ALLERGY_SUBSTANCES
        if substance in lowered
        and any(term in lowered for term in ("allerg", "anaphyl", "facial swelling", "rash"))
        and not NO_ALLERGY_PATTERN.search(lowered)
    }
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
