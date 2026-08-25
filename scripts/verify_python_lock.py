#!/usr/bin/env python3
"""Fail when the installed Python graph differs from the committed exact lock."""

from __future__ import annotations

import re
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-lock.txt"
PROJECT_PACKAGE = "nightingale-continuum-api"


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_versions() -> dict[str, str]:
    locked: dict[str, str] = {}
    for raw_line in LOCK.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        if separator != "==" or not name or not version:
            raise SystemExit(f"Invalid exact-lock line: {raw_line}")
        normalized = canonical(name)
        if normalized in locked:
            raise SystemExit(f"Duplicate package in exact lock: {name}")
        locked[normalized] = version
    return locked


def main() -> None:
    locked = locked_versions()
    installed = {
        canonical(distribution.metadata["Name"]): distribution.version
        for distribution in distributions()
        if canonical(distribution.metadata["Name"]) != PROJECT_PACKAGE
    }
    if installed == locked:
        print(f"Python exact lock passed: {len(locked)} packages match.")
        return

    missing = sorted(set(locked) - set(installed))
    unexpected = sorted(set(installed) - set(locked))
    mismatched = sorted(
        name for name in set(locked) & set(installed) if locked[name] != installed[name]
    )
    details = []
    if missing:
        details.append("missing: " + ", ".join(missing))
    if unexpected:
        details.append("unexpected: " + ", ".join(unexpected))
    if mismatched:
        details.append(
            "version mismatch: "
            + ", ".join(
                f"{name} locked={locked[name]} installed={installed[name]}" for name in mismatched
            )
        )
    raise SystemExit("Python exact lock failed:\n- " + "\n- ".join(details))


if __name__ == "__main__":
    main()
