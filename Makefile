SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help setup test test-browser lint build brief benchmark benchmark-cold security mutation verify api web clean-demo-data

help:
	@echo "Nightingale Continuum"
	@echo "  make setup      Install pinned backend and frontend dependencies"
	@echo "  make api        Run the FastAPI service on 127.0.0.1:8000"
	@echo "  make web        Run the Vite client on 127.0.0.1:5173"
	@echo "  make test       Run backend and frontend tests"
	@echo "  make test-browser  Run desktop/mobile Chromium workflow tests"
	@echo "  make lint       Run Python and TypeScript static checks"
	@echo "  make build      Build the production client"
	@echo "  make brief      Build and structurally verify the 3-page technical brief"
	@echo "  make benchmark  Measure the warm-path glance endpoint (API must be running)"
	@echo "  make benchmark-cold  Measure deterministic local API construction"
	@echo "  make security   Audit Python/npm dependencies and build SBOMs"
	@echo "  make mutation   Run critical-module mutation testing and export evidence"
	@echo "  make verify     Run all non-browser release gates"

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -e 'backend[dev]'
	.venv/bin/python -m pip install -r requirements-artifacts.txt
	npm --prefix frontend ci

api:
	PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

web:
	npm --prefix frontend run dev -- --host 127.0.0.1

test:
	NIGHTINGALE_DATABASE_URL=sqlite:// PYTHONPATH=backend .venv/bin/pytest backend/tests -W error --cov=backend/app --cov-branch --cov-fail-under=100
	npm --prefix frontend run test:coverage
	.venv/bin/python scripts/normalize_frontend_coverage.py

test-browser:
	npm --prefix frontend run test:e2e
	.venv/bin/python scripts/normalize_browser_e2e.py

lint:
	.venv/bin/ruff check --config backend/pyproject.toml backend/app backend/tests scripts
	.venv/bin/ruff format --config backend/pyproject.toml --check backend/app backend/tests scripts
	npm --prefix frontend run lint

build:
	npm --prefix frontend run build

brief:
	.venv/bin/python scripts/build_technical_brief.py

benchmark:
	.venv/bin/python scripts/benchmark_glance.py --output output/evidence/glance_benchmark.json

benchmark-cold:
	.venv/bin/python scripts/benchmark_cold_start.py

security:
	.venv/bin/python scripts/security_evidence.py

mutation:
	cd backend && NIGHTINGALE_DATABASE_URL=sqlite:// ../.venv/bin/mutmut run
	.venv/bin/python scripts/mutation_evidence.py

verify:
	./scripts/verify_all.sh

clean-demo-data:
	@echo "Remove local *.sqlite3 or *.db files manually after confirming their exact paths."
