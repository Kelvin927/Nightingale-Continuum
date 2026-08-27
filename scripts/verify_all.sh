#!/usr/bin/env bash
set -euo pipefail

if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv. Run: make setup"
  exit 2
fi

.venv/bin/python scripts/verify_python_lock.py
.venv/bin/ruff check --config backend/pyproject.toml backend/app backend/tests scripts
.venv/bin/ruff format --config backend/pyproject.toml --check backend/app backend/tests scripts
NIGHTINGALE_DATABASE_URL=sqlite:// PYTHONPATH=backend .venv/bin/pytest backend/tests -W error \
  --cov=backend/app --cov-branch --cov-report=term-missing \
  --cov-report=json:output/evidence/backend_coverage.json --cov-fail-under=100
npm --prefix frontend run lint
npm --prefix frontend run test:coverage
.venv/bin/python scripts/normalize_frontend_coverage.py
npm --prefix frontend run build
.venv/bin/python scripts/security_evidence.py
.venv/bin/python scripts/benchmark_cold_start.py

nightingale_api_port="$(.venv/bin/python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
nightingale_api_base_url="http://127.0.0.1:${nightingale_api_port}"
api_log="$(mktemp)"
NIGHTINGALE_DATABASE_URL=sqlite:// PYTHONPATH=backend .venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 --port "$nightingale_api_port" --no-access-log >"$api_log" 2>&1 &
api_pid=$!
cleanup_api() {
  kill "$api_pid" 2>/dev/null || true
  wait "$api_pid" 2>/dev/null || true
  rm -f "$api_log"
}
trap cleanup_api EXIT
nightingale_api_ready=0
for _ in {1..100}; do
  if NIGHTINGALE_API_BASE_URL="$nightingale_api_base_url" .venv/bin/python -c 'import os, httpx2; httpx2.get(os.environ["NIGHTINGALE_API_BASE_URL"] + "/health", timeout=0.2).raise_for_status()' 2>/dev/null; then
    nightingale_api_ready=1
    break
  fi
  if ! kill -0 "$api_pid" 2>/dev/null; then
    cat "$api_log"
    exit 1
  fi
  sleep 0.05
done
if [[ "$nightingale_api_ready" -ne 1 ]]; then
  cat "$api_log"
  echo "Isolated benchmark API did not become ready"
  exit 1
fi
.venv/bin/python scripts/benchmark_glance.py \
  --base-url "$nightingale_api_base_url" \
  --output output/evidence/glance_benchmark.json
cleanup_api
trap - EXIT

.venv/bin/python scripts/run_mutation.py
.venv/bin/python scripts/mutation_evidence.py
.venv/bin/python scripts/build_technical_brief.py
.venv/bin/python scripts/release_audit.py
git diff --check

echo "All non-browser verification gates passed."
