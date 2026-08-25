#!/usr/bin/env python3
"""Make frontend coverage evidence portable across checkout locations."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_DIR = ROOT / "output" / "evidence" / "frontend-coverage"
COVERAGE_FILES = ("coverage-final.json", "coverage-summary.json")
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[/\\]")


def portable_path(value: str) -> str:
    """Reduce an absolute coverage path to its stable repository-relative suffix."""
    normalized = value.replace("\\", "/")
    marker = "/frontend/"
    if marker in normalized and (normalized.startswith("/") or WINDOWS_ABSOLUTE.match(value)):
        return f"frontend/{normalized.split(marker, maxsplit=1)[1]}"
    return value


def normalize(value: object) -> object:
    if isinstance(value, dict):
        return {portable_path(str(key)): normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, str):
        return portable_path(value)
    return value


def main() -> None:
    for name in COVERAGE_FILES:
        path = COVERAGE_DIR / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        normalized = normalize(payload)
        path.write_text(
            json.dumps(normalized, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(path)


if __name__ == "__main__":
    main()
