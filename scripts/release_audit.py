#!/usr/bin/env python3
"""Fail closed on common candidate-submission packaging mistakes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = {
    "README.md",
    "ATTRIBUTION.txt",
    "requirements-lock.txt",
    "docs/DEMO_RUNBOOK.md",
    "docs/ASSURANCE_REPORT.md",
    "docs/INNOVATION_LEDGER.md",
    "docs/MUTATION_REVIEW.md",
    "docs/references/EVIDENCE_REGISTRY.md",
    "output/evidence/glance_benchmark.json",
    "output/evidence/cold_start_benchmark.json",
    "output/evidence/dependency_security.json",
    "output/evidence/backend_coverage.json",
    "output/evidence/browser_e2e.json",
    "output/evidence/frontend-coverage/coverage-summary.json",
    "output/evidence/mutation_testing.json",
    "output/evidence/python_dependency_audit.json",
    "output/evidence/python_sbom.cdx.json",
    "output/evidence/frontend_dependency_audit.json",
    "output/evidence/frontend_sbom.cdx.json",
    "output/evidence/release_verification.json",
    "output/pdf/nightingale_continuum_technical_brief.pdf",
    "backend/tests/test_rbac_scope.py",
    "backend/tests/test_revision_history.py",
    "backend/tests/test_highlight_provenance.py",
    "backend/tests/test_concurrent_edits.py",
    "backend/tests/test_self_learning_importance.py",
    "backend/tests/test_api_assurance.py",
    "backend/tests/test_domain_assurance.py",
    "backend/tests/test_failure_injection.py",
    "backend/tests/test_importance_semantics.py",
    "backend/tests/test_property_invariants.py",
    "backend/tests/test_semantic_contracts.py",
    "frontend/src/accessibility.test.tsx",
    "scripts/security_evidence.py",
    "scripts/mutation_evidence.py",
    "scripts/run_browser_tests.py",
    "scripts/run_mutation.py",
    "scripts/normalize_browser_e2e.py",
    "scripts/normalize_frontend_coverage.py",
    "scripts/benchmark_cold_start.py",
    "scripts/release_manifest.py",
    "scripts/verify_python_lock.py",
}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".webmanifest",
    ".yml",
    ".yaml",
}
FORBIDDEN_PARTS = {
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "playwright-report",
    "test-results",
    "tmp",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "OpenAI-style secret": re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
}
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
EXPECTED_MUTATION_COUNTS = {
    "audit": 196,
    "care": 248,
    "evaluation": 218,
    "importance": 701,
    "provenance": 105,
    "redaction": 113,
}
EXPECTED_MUTATION_TOTAL = sum(EXPECTED_MUTATION_COUNTS.values())


def git_paths(*arguments: str) -> list[str]:
    result = subprocess.run(  # noqa: S603
        ["/usr/bin/git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the Nightingale release package")
    parser.add_argument(
        "--allow-pending-manifest",
        action="store_true",
        help="Use only while verifying the source commit before clean-room evidence exists",
    )
    args = parser.parse_args()
    failures: list[str] = []
    tracked = set(git_paths("ls-files"))
    untracked = git_paths("ls-files", "--others", "--exclude-standard")

    if untracked:
        failures.append("untracked release files: " + ", ".join(untracked))

    missing = sorted(REQUIRED_PATHS - tracked)
    if missing:
        failures.append("required artifacts are not tracked: " + ", ".join(missing))

    for relative in sorted(tracked):
        path = Path(relative)
        if relative != ".env.example" and (
            path.name == ".env"
            or path.suffix in {".db", ".sqlite", ".sqlite3", ".pem", ".key"}
            or FORBIDDEN_PARTS.intersection(path.parts)
        ):
            failures.append(f"forbidden tracked path: {relative}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        content = (ROOT / path).read_text(encoding="utf-8")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                failures.append(f"possible {label} in {relative}")
        if CJK.search(content):
            failures.append(f"non-English CJK text in {relative}")

    seed = (ROOT / "backend/app/seed.py").read_text(encoding="utf-8")
    if "synthetic=True" not in seed:
        failures.append("seed data is not explicitly marked synthetic")

    lock_lines = [
        line.strip()
        for line in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    lock_names = [re.split(r"==", line, maxsplit=1)[0].lower() for line in lock_lines]
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+==[^=\s]+", line) for line in lock_lines):
        failures.append("Python dependency lock contains a non-exact or invalid requirement")
    if len(lock_names) != len(set(lock_names)):
        failures.append("Python dependency lock contains duplicate packages")

    evidence_checks = {
        "backend_coverage.json": lambda payload: (
            payload["totals"]["percent_statements_covered"] == 100.0
            and payload["totals"]["percent_branches_covered"] == 100.0
            and payload["totals"]["missing_lines"] == 0
            and payload["totals"]["missing_branches"] == 0
        ),
        "frontend-coverage/coverage-summary.json": lambda payload: all(
            payload["total"][metric]["pct"] == 100
            for metric in ("lines", "statements", "functions", "branches")
        ),
        "browser_e2e.json": lambda payload: (
            payload["stats"]["expected"] == 5
            and payload["stats"]["unexpected"] == 0
            and payload["stats"]["flaky"] == 0
            and payload["stats"]["skipped"] == 0
            and not payload["errors"]
        ),
        "dependency_security.json": lambda payload: (
            payload["passed"]
            and payload["python"]["known_vulnerabilities"] == 0
            and payload["python"]["dependencies_audited"] == len(lock_lines)
            and payload["python"]["editable_packages_skipped"] == 1
            and payload["frontend"]["known_vulnerabilities"] == 0
            and payload["frontend"]["dependencies_audited"] == 198
        ),
        "mutation_testing.json": lambda payload: (
            payload["acceptance"]["passed"]
            and payload["acceptance"]["all_mutants_checked"]
            and payload["acceptance"]["scope_baseline_matched"]
            and payload["configuration"]["expected_checked_by_module"] == EXPECTED_MUTATION_COUNTS
            and payload["configuration"]["expected_total"] == EXPECTED_MUTATION_TOTAL
            and {name: values["checked"] for name, values in payload["modules"].items()}
            == EXPECTED_MUTATION_COUNTS
            and payload["totals"]["total"] == EXPECTED_MUTATION_TOTAL
            and payload["totals"]["raw_score_percent"] >= 85.0
            and not payload["unchecked_mutants"]
        ),
        "cold_start_benchmark.json": lambda payload: (
            payload["acceptance"]["passed"]
            and not payload["failures"]
            and payload["samples_successful"] == payload["samples_requested"]
        ),
        "glance_benchmark.json": lambda payload: (
            payload["acceptance"]["passed"]
            and not payload["failures"]
            and payload["samples_successful"] == payload["samples_requested"]
        ),
    }
    for relative, predicate in evidence_checks.items():
        evidence_path = ROOT / "output" / "evidence" / relative
        if not evidence_path.exists():
            failures.append(f"missing evidence file: output/evidence/{relative}")
            continue
        try:
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            if not predicate(payload):
                failures.append(f"evidence acceptance failed: output/evidence/{relative}")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"invalid evidence file output/evidence/{relative}: {exc}")

    for name in ("coverage-final.json", "coverage-summary.json"):
        coverage_path = ROOT / "output" / "evidence" / "frontend-coverage" / name
        try:
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            for source, details in coverage.items():
                if source != "total" and Path(source).is_absolute():
                    failures.append(f"absolute source path in frontend coverage evidence: {name}")
                    break
                if isinstance(details, dict):
                    reported_path = details.get("path")
                    if isinstance(reported_path, str) and (
                        Path(reported_path).is_absolute()
                        or re.match(r"^[A-Za-z]:[/\\]", reported_path)
                    ):
                        failures.append(
                            f"absolute reported path in frontend coverage evidence: {name}"
                        )
                        break
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"invalid frontend coverage path evidence {name}: {exc}")

    browser_evidence_path = ROOT / "output" / "evidence" / "browser_e2e.json"
    try:
        browser_evidence = json.loads(browser_evidence_path.read_text(encoding="utf-8"))
        pending: list[object] = [browser_evidence]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str) and (
                Path(value).is_absolute() or re.match(r"^[A-Za-z]:[/\\]", value)
            ):
                failures.append("absolute path in browser E2E evidence")
                break
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"invalid browser E2E path evidence: {exc}")

    manifest_path = ROOT / "output" / "evidence" / "release_verification.json"
    if manifest_path.exists() and not args.allow_pending_manifest:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source_commit = manifest["verified_source_commit"]
            if manifest["schema_version"] != 2:
                failures.append("release manifest schema_version must be 2")
            if not manifest["clean_room"]["passed"]:
                failures.append("release manifest does not record a passing clean-room run")
            if not all(
                manifest["clean_room"][key]
                for key in (
                    "fresh_git_clone",
                    "fresh_python_venv",
                    "npm_ci",
                    "make_verify",
                    "source_working_tree_clean_before_manifest",
                )
            ):
                failures.append("release manifest clean-room evidence is incomplete")
            ancestor = subprocess.run(  # noqa: S603 - fixed Git executable and manifest hash
                ["/usr/bin/git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
                cwd=ROOT,
                check=False,
            )
            if ancestor.returncode != 0:
                failures.append("verified source commit is not an ancestor of HEAD")
            if any(
                not re.fullmatch(r"[0-9a-f]{64}", value) for value in manifest["artifacts"].values()
            ):
                failures.append("release manifest contains an invalid SHA-256 digest")
            expected_artifacts = {
                "output/pdf/nightingale_continuum_technical_brief.pdf",
                "output/evidence/backend_coverage.json",
                "output/evidence/browser_e2e.json",
                "output/evidence/frontend-coverage/coverage-final.json",
                "output/evidence/frontend-coverage/coverage-summary.json",
                "output/evidence/dependency_security.json",
                "output/evidence/python_dependency_audit.json",
                "output/evidence/frontend_dependency_audit.json",
                "output/evidence/python_sbom.cdx.json",
                "output/evidence/frontend_sbom.cdx.json",
                "output/evidence/mutation_testing.json",
                "output/evidence/glance_benchmark.json",
                "output/evidence/cold_start_benchmark.json",
            }
            if set(manifest["artifacts"]) != expected_artifacts:
                failures.append("release manifest artifact set is incomplete or unexpected")
            else:
                for relative, expected_digest in manifest["artifacts"].items():
                    actual_digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                    if actual_digest != expected_digest:
                        failures.append(f"release artifact digest mismatch: {relative}")
            manifest_commit = manifest["manifest_created_from_commit"]
            manifest_ancestor = subprocess.run(  # noqa: S603 - fixed Git executable and hash
                ["/usr/bin/git", "merge-base", "--is-ancestor", manifest_commit, "HEAD"],
                cwd=ROOT,
                check=False,
            )
            if manifest_ancestor.returncode != 0:
                failures.append("manifest creation commit is not an ancestor of HEAD")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"invalid release verification manifest: {exc}")

    brief_path = ROOT / "output/pdf/nightingale_continuum_technical_brief.pdf"
    if brief_path.exists():
        reader = PdfReader(str(brief_path))
        if len(reader.pages) != 3:
            failures.append(f"technical brief must have 3 pages, found {len(reader.pages)}")
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        for statement in ("Synthetic data only", "Prototype - not for clinical use"):
            if statement not in extracted:
                failures.append(f"technical brief is missing disclaimer: {statement}")

    if failures:
        formatted = "\n".join(f"- {failure}" for failure in failures)
        raise SystemExit(f"Release audit failed:\n{formatted}")

    print(
        "Release audit passed: tracked files intentional, required artifacts present, "
        "coverage/security/mutation/performance evidence accepted, no common secrets "
        "or CJK project text, synthetic marker present, PDF valid."
    )


if __name__ == "__main__":
    main()
