from __future__ import annotations

from app.care import build_merge_assistance


def test_merge_assistance_handles_trivial_three_way_states() -> None:
    identical = build_merge_assistance("base", "same", "same")
    assert identical == {
        "status": "identical",
        "auto_merge_safe": True,
        "merged_content": "same",
        "conflicting_hunks": [],
    }

    current_only = build_merge_assistance("base", "base", "current")
    assert current_only["status"] == "current_only"
    assert current_only["merged_content"] == "current"

    proposed_only = build_merge_assistance("base", "proposed", "base")
    assert proposed_only["status"] == "proposed_only"
    assert proposed_only["merged_content"] == "proposed"


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
