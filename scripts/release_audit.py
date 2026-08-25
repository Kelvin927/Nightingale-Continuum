#!/usr/bin/env python3
"""Fail closed on common candidate-submission packaging mistakes."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = {
    "README.md",
    "ATTRIBUTION.txt",
    "docs/DEMO_RUNBOOK.md",
    "docs/INNOVATION_LEDGER.md",
    "docs/references/EVIDENCE_REGISTRY.md",
    "output/evidence/glance_benchmark.json",
    "output/evidence/release_verification.json",
    "output/pdf/nightingale_continuum_technical_brief.pdf",
    "backend/tests/test_rbac_scope.py",
    "backend/tests/test_revision_history.py",
    "backend/tests/test_highlight_provenance.py",
    "backend/tests/test_concurrent_edits.py",
    "backend/tests/test_self_learning_importance.py",
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


def git_paths(*arguments: str) -> list[str]:
    result = subprocess.run(  # noqa: S603
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> None:
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

    brief_path = ROOT / "output/pdf/nightingale_continuum_technical_brief.pdf"
    if brief_path.exists():
        reader = PdfReader(str(brief_path))
        if len(reader.pages) != 3:
            failures.append(
                f"technical brief must have 3 pages, found {len(reader.pages)}"
            )
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        for statement in ("Synthetic data only", "Prototype - not for clinical use"):
            if statement not in extracted:
                failures.append(f"technical brief is missing disclaimer: {statement}")

    if failures:
        formatted = "\n".join(f"- {failure}" for failure in failures)
        raise SystemExit(f"Release audit failed:\n{formatted}")

    print(
        "Release audit passed: tracked files intentional, required artifacts present, "
        "no common secrets or CJK project text, synthetic marker present, PDF valid."
    )


if __name__ == "__main__":
    main()
