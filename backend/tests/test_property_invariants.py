from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.audit import _canonical_json
from app.care import content_hash, version_diff
from app.constants import RISK_WEIGHT
from app.evaluation import _target_probability
from app.importance import base_score
from app.models import EntryVersion
from app.redaction import Finding, _normalize_findings, redact_text

DETERMINISTIC = settings(max_examples=150, derandomize=True, deadline=None)
ASCII_WORD = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=16)
DIGIT = st.sampled_from(tuple("0123456789"))


@DETERMINISTIC
@given(
    first=ASCII_WORD,
    last=ASCII_WORD,
    digits=st.lists(DIGIT, min_size=7, max_size=7).map("".join),
    phone_tail=st.lists(DIGIT, min_size=7, max_size=7).map("".join),
    prefix=st.sampled_from(("S", "T", "F", "G", "M")),
    suffix=st.sampled_from(tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")),
    phone_prefix=st.sampled_from(("8", "9")),
)
def test_redaction_removes_generated_identifiers_and_receipt_is_exact(
    first: str,
    last: str,
    digits: str,
    phone_tail: str,
    prefix: str,
    suffix: str,
    phone_prefix: str,
):
    name = f"{first.title()} {last.title()}"
    nric = f"{prefix}{digits}{suffix}"
    phone = f"{phone_prefix}{phone_tail}"
    email = f"{first}.{last}@example.org"
    raw = f"Patient {name}; NRIC {nric}; mobile {phone}; email {email}."

    result = redact_text(raw, known_names=[name])

    for secret in (name, nric, phone, email):
        assert secret.casefold() not in result.text.casefold()
    assert result.receipt.passed is True
    assert result.receipt.entity_counts == {
        "PERSON": 1,
        "SG_NRIC_FIN": 1,
        "PHONE_NUMBER": 1,
        "EMAIL_ADDRESS": 1,
    }
    assert result.receipt.sanitized_sha256 == hashlib.sha256(result.text.encode()).hexdigest()
    assert all(raw[item.start : item.end].strip() for item in result.findings)


@DETERMINISTIC
@given(
    spans=st.lists(
        st.tuples(
            st.integers(min_value=-5, max_value=80),
            st.integers(min_value=-3, max_value=30),
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        ),
        min_size=0,
        max_size=35,
    )
)
def test_normalized_findings_are_ordered_valid_and_non_overlapping(spans):
    findings = [
        Finding("SYNTHETIC", start, start + length, confidence)
        for start, length, confidence in spans
    ]

    normalized = _normalize_findings(findings)

    assert normalized == sorted(normalized, key=lambda item: item.start)
    assert all(item.start < item.end for item in normalized)
    assert all(
        left.end <= right.start for left, right in zip(normalized, normalized[1:], strict=False)
    )
    assert all(item in findings for item in normalized)


@DETERMINISTIC
@given(
    low=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    delta=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    risk=st.sampled_from(("critical", "high", "medium", "low")),
)
def test_shadow_target_probability_is_bounded_and_monotone(low: float, delta: float, risk: str):
    lower = _target_probability({"base_score": low, "risk_level": risk})
    upper = _target_probability({"base_score": low + delta, "risk_level": risk})

    assert 0.05 <= lower <= upper <= 0.95


@DETERMINISTIC
@given(
    age_days=st.integers(min_value=0, max_value=3650),
    unresolved=st.booleans(),
    pinned=st.booleans(),
)
def test_base_score_preserves_safety_order_and_recency_decay(
    age_days: int, unresolved: bool, pinned: bool
):
    now = datetime(2026, 8, 26, tzinfo=UTC)
    created_at = now - timedelta(days=age_days)
    scores = {
        risk: base_score(
            risk_level=risk,
            tags=["medication"],
            created_at=created_at,
            now=now,
            unresolved_action=unresolved,
            explicitly_pinned=pinned,
        )[0]
        for risk in RISK_WEIGHT
    }

    assert scores["critical"] > scores["high"] > scores["medium"] > scores["low"]
    older_score = base_score(
        risk_level="high",
        tags=["medication"],
        created_at=created_at - timedelta(days=1),
        now=now,
        unresolved_action=unresolved,
        explicitly_pinned=pinned,
    )[0]
    assert older_score <= scores["high"]


@DETERMINISTIC
@given(
    content=st.text(max_size=500),
    metadata=st.dictionaries(
        keys=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12),
        values=st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=30)),
        max_size=12,
    ),
)
def test_hashes_and_canonical_serialization_are_deterministic(content: str, metadata: dict):
    expected = hashlib.sha256(content.encode()).hexdigest()
    assert content_hash(content) == expected == content_hash(content)
    assert _canonical_json(metadata) == _canonical_json(dict(reversed(list(metadata.items()))))


@DETERMINISTIC
@given(content=st.text(max_size=500))
def test_version_diff_is_empty_for_identical_content(content: str):
    older = EntryVersion(content=content, version=1)
    newer = EntryVersion(content=content, version=2)
    assert version_diff(older, newer) == []
