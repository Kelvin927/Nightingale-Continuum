#!/usr/bin/env bash
set -euo pipefail

if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv. Run: make setup"
  exit 2
fi

.venv/bin/ruff check backend/app backend/tests scripts
.venv/bin/ruff format --check backend/app backend/tests scripts
PYTHONPATH=backend .venv/bin/pytest backend/tests --cov=backend/app --cov-report=term-missing --cov-fail-under=85
npm --prefix frontend run test
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=high
.venv/bin/python scripts/build_technical_brief.py
.venv/bin/python scripts/release_audit.py
git diff --check

echo "All non-browser verification gates passed."
