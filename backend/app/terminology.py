"""Create deterministic, reviewable medication-and-dose evidence for delivery gates.

The built-in vocabulary exists only to make the synthetic prototype reproducible. It is
not a formulary, a prescribing engine, or a substitute for a deployed terminology service.
"""

from __future__ import annotations

import re
from decimal import Decimal

POLICY_VERSION = "medication-confirmation/2026-09-05"
ADAPTER_VERSION = "local-demo-vocabulary/1.0"
RXNORM_EXACT_LOOKUP = "https://rxnav.nlm.nih.gov/REST/rxcui.json?name={isolated_term}"

MEDICATIONS = {
    "amlodipine": "demo-med:amlodipine",
    "amoxicillin": "demo-med:amoxicillin",
    "insulin": "demo-med:insulin",
    "lisinopril": "demo-med:lisinopril",
    "metformin": "demo-med:metformin",
    "penicillin": "demo-med:penicillin",
    "warfarin": "demo-med:warfarin",
}
MEDICATION_PATTERN = re.compile(
    rf"\b(?P<name>{'|'.join(sorted(MEDICATIONS, key=len, reverse=True))})\b",
    re.IGNORECASE,
)
DOSE_PATTERN = re.compile(
    r"(?<![\w.])(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mcg|ug|µg|mg|g|ml|units?)(?!\w)",
    re.IGNORECASE,
)
UNSUPPORTED_UNIT_PATTERN = re.compile(
    r"(?<![\w.])(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mgs|milligrams?|micrograms?|grams?|millilit(?:er|re)s?)(?!\w)",
    re.IGNORECASE,
)
GENERIC_SIGNAL_PATTERN = re.compile(
    r"\b(?:dose|dosage|medication|medicine|tablet|capsule|prescription)\b",
    re.IGNORECASE,
)
SEMANTIC_CONTRAST_PATTERN = re.compile(
    r"\b(?:changed?\s+from|instead\s+of|rather\s+than|not|correction|increase|decrease)\b",
    re.IGNORECASE,
)
SENTENCE_BREAK_PATTERN = re.compile(r"[!?\n]|(?<!\d)\.(?!\d)")
UNIT_NORMALIZATION = {
    "g": "g",
    "mcg": "ug",
    "mg": "mg",
    "ml": "mL",
    "ug": "ug",
    "µg": "ug",
    "μg": "ug",
    "unit": "{unit}",
    "units": "{unit}",
}
DECISION_BOUNDARY = (
    "A terminology match checks only that a medication name and dose expression are "
    "machine-addressable. It does not establish prescription accuracy, patient-specific "
    "appropriateness, route, frequency, interactions, contraindications, or clinical intent."
)


def _normalized_decimal(value: str) -> str:
    normalized = format(Decimal(value), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    breaks = [match.start() for match in SENTENCE_BREAK_PATTERN.finditer(text)]
    left = max((position for position in breaks if position < start), default=-1) + 1
    right_candidates = [position for position in breaks if position >= end]
    return left, min(right_candidates) if right_candidates else len(text)


def _nearest_medication(
    text: str,
    dose: re.Match[str],
    medications: list[re.Match[str]],
) -> re.Match[str] | None:
    sentence_start, sentence_end = _sentence_bounds(text, dose.start(), dose.end())
    in_sentence = [
        item
        for item in medications
        if item.start() >= sentence_start and item.end() <= sentence_end
    ]
    before = [item for item in in_sentence if item.end() <= dose.start()]
    if before:
        candidate = max(before, key=lambda item: item.end())
        if dose.start() - candidate.end() <= 64:
            return candidate
    after = [item for item in in_sentence if item.start() >= dose.end()]
    if after:
        candidate = min(after, key=lambda item: item.start())
        if candidate.start() - dose.end() <= 32:
            return candidate
    return None


def assess_medication_terminology(text: str) -> dict:
    """Return a versioned evidence receipt without inferring clinical correctness."""

    medication_matches = list(MEDICATION_PATTERN.finditer(text))
    dose_matches = list(DOSE_PATTERN.finditer(text))
    unsupported_matches = list(UNSUPPORTED_UNIT_PATTERN.finditer(text))
    medication_mentions = [
        {
            "normalized_name": match.group("name").casefold(),
            "local_terminology_id": MEDICATIONS[match.group("name").casefold()],
            "source_text": match.group(0),
            "source_start": match.start(),
            "source_end": match.end(),
            "reference_state": "local_demo_vocabulary_only",
        }
        for match in medication_matches
    ]
    dose_mentions: list[dict] = []
    unresolved: list[dict] = []
    dose_values_by_medication: dict[str, set[str]] = {}

    for dose in dose_matches:
        medication = _nearest_medication(text, dose, medication_matches)
        normalized_value = _normalized_decimal(dose.group("value"))
        normalized_unit = UNIT_NORMALIZATION[dose.group("unit").casefold()]
        record = {
            "source_text": dose.group(0),
            "source_start": dose.start(),
            "source_end": dose.end(),
            "normalized_value": normalized_value,
            "normalized_unit": normalized_unit,
            "medication_name": (
                None if medication is None else medication.group("name").casefold()
            ),
        }
        dose_mentions.append(record)
        if medication is None:
            unresolved.append(
                {
                    "code": "unlinked_dose",
                    "source_text": dose.group(0),
                    "source_start": dose.start(),
                    "source_end": dose.end(),
                    "message": "This dose is not linked to a supported medication name.",
                }
            )
        else:
            name = medication.group("name").casefold()
            dose_values_by_medication.setdefault(name, set()).add(
                f"{normalized_value} {normalized_unit}"
            )
        if Decimal(dose.group("value")) <= 0:
            unresolved.append(
                {
                    "code": "non_positive_dose",
                    "source_text": dose.group(0),
                    "source_start": dose.start(),
                    "source_end": dose.end(),
                    "message": "A zero or negative dose cannot pass the structured release gate.",
                }
            )

    for unsupported in unsupported_matches:
        unresolved.append(
            {
                "code": "unsupported_dose_unit",
                "source_text": unsupported.group(0),
                "source_start": unsupported.start(),
                "source_end": unsupported.end(),
                "message": "Use a supported, normalized dose unit before delivery.",
            }
        )

    generic_signal = GENERIC_SIGNAL_PATTERN.search(text) is not None
    has_signal = bool(medication_matches or dose_matches or unsupported_matches or generic_signal)
    if unresolved:
        status = "blocked_unresolved"
    elif dose_matches:
        status = "structured_review_ready"
    elif has_signal:
        status = "human_review_only"
    else:
        status = "not_applicable"
    conflicting_values = any(len(values) > 1 for values in dose_values_by_medication.values())

    return {
        "policy_version": POLICY_VERSION,
        "status": status,
        "dose_sensitive": has_signal,
        "human_confirmation_required": has_signal,
        "semantic_review_required": conflicting_values
        or bool(SEMANTIC_CONTRAST_PATTERN.search(text)),
        "release_permitted_after_confirmation": not unresolved,
        "external_reference_performed": False,
        "adapter": {
            "name": "project_authored_local_demo_vocabulary",
            "version": ADAPTER_VERSION,
            "mode": "synthetic_rehearsal_only",
            "production_target": "NLM RxNorm exact lookup plus a clinic-approved local formulary",
            "production_endpoint_pattern": RXNORM_EXACT_LOOKUP,
        },
        "medication_mentions": medication_mentions,
        "dose_mentions": dose_mentions,
        "unresolved": unresolved,
        "decision_boundary": DECISION_BOUNDARY,
    }
