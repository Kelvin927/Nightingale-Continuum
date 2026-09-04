from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.care import _edits_overlap, _version_snapshot, build_merge_assistance


def test_merge_assistance_handles_trivial_three_way_states() -> None:
    identical = build_merge_assistance("base", "same", "same")
    assert identical == {
        "status": "identical",
        "auto_merge_safe": True,
        "merged_content": "same",
        "conflicting_hunks": [],
    }

    current_only = build_merge_assistance("base", "base", "current")
    assert current_only == {
        "status": "current_only",
        "auto_merge_safe": True,
        "merged_content": "current",
        "conflicting_hunks": [],
    }

    proposed_only = build_merge_assistance("base", "proposed", "base")
    assert proposed_only == {
        "status": "proposed_only",
        "auto_merge_safe": True,
        "merged_content": "proposed",
        "conflicting_hunks": [],
    }


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ((1, 1, []), (1, 1, []), True),
        ((1, 1, []), (2, 2, []), False),
        ((1, 1, []), (1, 3, []), True),
        ((3, 3, []), (1, 3, []), True),
        ((4, 4, []), (1, 3, []), False),
        ((1, 3, []), (1, 1, []), True),
        ((1, 3, []), (3, 3, []), True),
        ((1, 3, []), (4, 4, []), False),
        ((1, 2, []), (2, 3, []), False),
        ((1, 3, []), (2, 4, []), True),
    ],
)
def test_edit_overlap_boundary_contract(left, right, expected) -> None:
    assert _edits_overlap(left, right) is expected


def test_version_snapshot_is_an_exact_immutable_contract() -> None:
    created_at = datetime(2026, 9, 5, 2, 3, 4, tzinfo=UTC)
    version = SimpleNamespace(
        id="version-7",
        version=7,
        content="Synthetic content",
        content_hash="a" * 64,
        created_at=created_at,
    )
    assert _version_snapshot(version) == {
        "version_id": "version-7",
        "version": 7,
        "content": "Synthetic content",
        "content_hash": "a" * 64,
        "created_at": "2026-09-05T02:03:04+00:00",
    }


def test_merge_assistance_proposes_only_non_overlapping_line_edits() -> None:
    result = build_merge_assistance(
        "allergy: pending\nmedication: 10 mg\nfollow-up: pending\n",
        "allergy: reviewed\nmedication: 10 mg\nfollow-up: pending\n",
        "allergy: pending\nmedication: 10 mg\nfollow-up: booked\n",
    )
    assert result == {
        "status": "non_overlapping_draft",
        "auto_merge_safe": True,
        "merged_content": "allergy: reviewed\nmedication: 10 mg\nfollow-up: booked\n",
        "conflicting_hunks": [],
    }


def test_merge_assistance_requires_manual_review_for_overlapping_changes() -> None:
    result = build_merge_assistance(
        "dose: 10 mg\n",
        "dose: 20 mg\n",
        "dose: 30 mg\n",
    )
    assert result["status"] == "manual_review_required"
    assert result["auto_merge_safe"] is False
    assert result["merged_content"] is None
    assert result["conflicting_hunks"] == [
        {
            "base_start_line": 1,
            "base_end_line": 1,
            "proposed_text": "dose: 20 mg\n",
            "current_text": "dose: 30 mg\n",
        }
    ]


def test_merge_assistance_preserves_multiline_text_inside_conflicting_hunks() -> None:
    result = build_merge_assistance(
        "dose: 10 mg\nfrequency: daily\nfollow-up: pending\n",
        "dose: 20 mg\nfrequency: twice daily\nfollow-up: pending\n",
        "dose: 30 mg\nfrequency: weekly\nfollow-up: pending\n",
    )
    assert result["conflicting_hunks"] == [
        {
            "base_start_line": 1,
            "base_end_line": 2,
            "proposed_text": "dose: 20 mg\nfrequency: twice daily\n",
            "current_text": "dose: 30 mg\nfrequency: weekly\n",
        }
    ]


def test_merge_assistance_treats_competing_insertions_as_overlap() -> None:
    result = build_merge_assistance(
        "first\nlast\n",
        "first\nproposed\nlast\n",
        "first\ncurrent\nlast\n",
    )
    assert result["status"] == "manual_review_required"
    assert result["conflicting_hunks"][0]["base_start_line"] == 2


def test_merge_assistance_is_conservative_at_edit_boundaries() -> None:
    insert_against_replace = build_merge_assistance(
        "first\nsecond\nthird\n",
        "first\ninserted\nsecond\nthird\n",
        "first\nreplaced\nthird\n",
    )
    replace_against_insert = build_merge_assistance(
        "first\nsecond\nthird\n",
        "first\nreplaced\nthird\n",
        "first\ninserted\nsecond\nthird\n",
    )
    disjoint_insertions = build_merge_assistance(
        "first\nsecond\nthird\n",
        "proposed\nfirst\nsecond\nthird\n",
        "first\nsecond\nthird\ncurrent\n",
    )
    assert insert_against_replace["auto_merge_safe"] is False
    assert replace_against_insert["auto_merge_safe"] is False
    assert disjoint_insertions["auto_merge_safe"] is True
    assert disjoint_insertions["merged_content"] == ("proposed\nfirst\nsecond\nthird\ncurrent\n")
