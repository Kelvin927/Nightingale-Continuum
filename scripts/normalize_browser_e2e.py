#!/usr/bin/env python3
"""Make Playwright JSON evidence portable across checkout locations."""

from __future__ import annotations

import json
from pathlib import Path

from normalize_frontend_coverage import normalize

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "output" / "evidence" / "browser_e2e.json"


def main() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    normalized = normalize(payload)
    if isinstance(normalized, dict):
        config = normalized.get("config")
        if isinstance(config, dict):
            arguments = config.get("argv")
            if isinstance(arguments, list) and arguments and isinstance(arguments[0], str):
                arguments[0] = Path(arguments[0]).name
    REPORT.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(REPORT)


if __name__ == "__main__":
    main()
