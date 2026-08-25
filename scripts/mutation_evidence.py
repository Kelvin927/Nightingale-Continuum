#!/usr/bin/env python3
"""Export an honest mutation-testing scorecard from the critical backend modules."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Nightingale mutation evidence")
    parser.add_argument("--minimum-score", type=float, default=85.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "evidence" / "mutation_testing.json",
    )
    args = parser.parse_args()
    export = subprocess.run(  # noqa: S603 - fixed local executable and arguments
        [str(ROOT / ".venv" / "bin" / "mutmut"), "export-cicd-stats"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    stats_path = BACKEND / "mutants" / "mutmut-cicd-stats.json"
    if export.returncode != 0 or not stats_path.exists():
        diagnostic = export.stderr.strip() or export.stdout.strip() or "missing stats file"
        raise SystemExit(f"Could not export mutation statistics: {diagnostic}")
    totals = json.loads(stats_path.read_text(encoding="utf-8"))

    modules: dict[str, dict] = {}
    all_survivors: list[str] = []
    unchecked: list[str] = []
    for metadata_path in sorted((BACKEND / "mutants" / "app").glob("*.meta")):
        verdicts = json.loads(metadata_path.read_text(encoding="utf-8"))["exit_code_by_key"]
        counts = Counter(verdicts.values())
        survivors = sorted(key for key, verdict in verdicts.items() if verdict == 0)
        unchecked.extend(sorted(key for key, verdict in verdicts.items() if verdict is None))
        all_survivors.extend(survivors)
        checked = counts[0] + counts[1]
        modules[metadata_path.stem.removesuffix(".py")] = {
            "killed": counts[1],
            "survived": counts[0],
            "checked": checked,
            "score_percent": round(100 * counts[1] / checked, 2) if checked else 0.0,
        }

    checked = totals["killed"] + totals["survived"]
    score = 100 * totals["killed"] / checked if checked else 0.0
    zero_error_outcomes = all(
        totals[key] == 0
        for key in (
            "no_tests",
            "skipped",
            "suspicious",
            "timeout",
            "segfault",
            "check_was_interrupted_by_user",
        )
    )
    passed = (
        not unchecked
        and checked == totals["total"]
        and score >= args.minimum_score
        and zero_error_outcomes
    )
    evidence = {
        "generated_at": datetime.now(UTC).isoformat(),
        "tool": "mutmut 3.7.0",
        "scope": sorted(modules),
        "configuration": {
            "mutate_only_covered_lines": True,
            "backend_statement_and_branch_coverage_required_percent": 100,
            "minimum_raw_mutation_score_percent": args.minimum_score,
        },
        "totals": {
            **totals,
            "checked": checked,
            "raw_score_percent": round(score, 2),
        },
        "modules": modules,
        "surviving_mutants": sorted(all_survivors),
        "unchecked_mutants": unchecked,
        "acceptance": {
            "all_mutants_checked": not unchecked and checked == totals["total"],
            "no_timeout_or_invalid_outcomes": zero_error_outcomes,
            "raw_score_threshold_passed": score >= args.minimum_score,
            "passed": passed,
        },
        "interpretation": [
            (
                "The raw score penalizes every survivor; no survivor is silently "
                "reclassified as equivalent."
            ),
            "Surviving mutants are retained for reviewer inspection and future test refinement.",
            (
                "Mutation score measures test sensitivity, not absence of defects or "
                "clinical validity."
            ),
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Mutation evidence: {totals['killed']}/{checked} killed "
        f"({score:.2f}%), {totals['survived']} survivors, "
        f"{len(unchecked)} unchecked."
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
