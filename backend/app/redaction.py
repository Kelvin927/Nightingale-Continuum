"""Redact synthetic identifiers before text reaches any provider boundary."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass

from .constants import REDACTION_VERSION


@dataclass(frozen=True)
class Finding:
    entity_type: str
    start: int
    end: int
    confidence: float


@dataclass(frozen=True)
class RedactionReceipt:
    detector_version: str
    entity_counts: dict[str, int]
    sanitized_sha256: str
    clinical_anchor_count: int
    clinical_anchors_preserved: bool
    passed: bool


@dataclass(frozen=True)
class RedactionResult:
    text: str
    findings: tuple[Finding, ...]
    receipt: RedactionReceipt


PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    (
        "SG_NRIC_FIN",
        re.compile(r"(?<![A-Z0-9])[STFGM]\d{7}[A-Z](?![A-Z0-9])", re.IGNORECASE),
        0.99,
    ),
    (
        "PHONE_NUMBER",
        re.compile(
            r"(?<!\w)(?:\+?65[\s.-]?)?(?:6|8|9)\d{3}[\s.-]?\d{4}(?!\w)|"
            r"(?<!\w)\+?\d{1,3}[\s.-]?\(?\d{2,4}\)?(?:[\s.-]?\d{2,4}){2,3}(?!\w)"
        ),
        0.96,
    ),
    (
        "EMAIL_ADDRESS",
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        0.99,
    ),
    (
        "PERSON",
        re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr)\.?\s+[A-Z][a-z]+(?:[ -][A-Z][a-z]+){0,2}\b"),
        0.86,
    ),
    (
        "PERSON",
        re.compile(
            r"\b(?:my name is|patient name[:\s]+|I am)\s+"
            r"([A-Z][a-z]+(?:[ -][A-Z][a-z]+){1,2})\b",
            re.IGNORECASE,
        ),
        0.84,
    ),
)

CLINICAL_ANCHOR_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mcg|mg|g|ml|units?)\b|"
    r"\b(?:allerg(?:y|ic)|anaphylaxis|medication|dose|penicillin|lisinopril|metformin)\b",
    re.IGNORECASE,
)


def _clinical_anchor_signature(text: str) -> Counter[str]:
    """Count safety-relevant tokens whose loss could change clinical meaning."""

    return Counter(
        re.sub(r"\s+", "", match.group()).casefold()
        for match in CLINICAL_ANCHOR_PATTERN.finditer(text)
    )


def _known_name_findings(text: str, known_names: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for name in known_names:
        cleaned = name.strip()
        if len(cleaned) < 2:
            continue
        for match in re.finditer(re.escape(cleaned), text, re.IGNORECASE):
            findings.append(Finding("PERSON", match.start(), match.end(), 0.99))
    return findings


def _normalize_findings(findings: list[Finding]) -> list[Finding]:
    ordered = sorted(findings, key=lambda item: item.start)
    normalized: list[Finding] = []
    for candidate in ordered:
        if candidate.start >= candidate.end:
            continue
        overlapping = [existing for existing in normalized if candidate.start < existing.end]
        if not overlapping:
            normalized.append(candidate)
            continue
        strongest = max(
            overlapping + [candidate], key=lambda item: (item.confidence, item.end - item.start)
        )
        normalized = [item for item in normalized if item not in overlapping]
        normalized.append(strongest)
    return sorted(normalized, key=lambda item: item.start)


def redact_text(text: str, *, known_names: list[str] | None = None) -> RedactionResult:
    if not text.strip():
        raise ValueError("Text must not be empty")

    findings: list[Finding] = []
    for entity_type, pattern, confidence in PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span(1) if match.lastindex else match.span()
            findings.append(Finding(entity_type, start, end, confidence))
    findings.extend(_known_name_findings(text, known_names or []))
    normalized = _normalize_findings(findings)

    sanitized = text
    for item in reversed(normalized):
        sanitized = sanitized[: item.start] + f"<{item.entity_type}>" + sanitized[item.end :]

    counts: dict[str, int] = {}
    for item in normalized:
        counts[item.entity_type] = counts.get(item.entity_type, 0) + 1
    original_anchors = _clinical_anchor_signature(text)
    sanitized_anchors = _clinical_anchor_signature(sanitized)
    clinical_anchors_preserved = original_anchors == sanitized_anchors
    privacy_entities_removed = all(
        text[item.start : item.end].casefold() not in sanitized.casefold() for item in normalized
    )
    receipt = RedactionReceipt(
        detector_version=REDACTION_VERSION,
        entity_counts=counts,
        sanitized_sha256=hashlib.sha256(sanitized.encode()).hexdigest(),
        clinical_anchor_count=sum(original_anchors.values()),
        clinical_anchors_preserved=clinical_anchors_preserved,
        passed=privacy_entities_removed and clinical_anchors_preserved,
    )
    return RedactionResult(sanitized, tuple(normalized), receipt)
