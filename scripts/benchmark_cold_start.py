#!/usr/bin/env python3
"""Measure deterministic local API construction and seeded-database cold starts."""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def benchmark(samples: int, threshold_ms: float) -> dict:
    sys.path.insert(0, str(ROOT / "backend"))
    create_app = importlib.import_module("app.main").create_app
    durations: list[float] = []
    failures: list[dict] = []
    for index in range(samples):
        started = time.perf_counter_ns()
        application = None
        try:
            application = create_app(database_url="sqlite://", seed_data=True)
            duration_ms = (time.perf_counter_ns() - started) / 1_000_000
            with application.state.database.session() as session:
                health_ready = session.bind is not None
            if not health_ready:
                failures.append({"sample": index, "failure": "database_not_bound"})
            durations.append(duration_ms)
        except Exception as exc:  # noqa: BLE001 - evidence must retain any failure class
            failures.append({"sample": index, "failure": type(exc).__name__})
        finally:
            if application is not None:
                application.state.database.engine.dispose()

    if not durations:
        raise RuntimeError("Cold-start benchmark produced no successful observations")
    p95 = percentile(durations, 0.95)
    return {
        "measurement": (
            "Cold construction of FastAPI routes, in-memory SQLite schema, and synthetic seed data"
        ),
        "recorded_at": datetime.now(UTC).isoformat(),
        "samples_requested": samples,
        "samples_successful": len(durations),
        "failures": failures,
        "latency_ms": {
            "minimum": round(min(durations), 3),
            "median": round(statistics.median(durations), 3),
            "p95": round(p95, 3),
            "p99": round(percentile(durations, 0.99), 3),
            "maximum": round(max(durations), 3),
            "mean": round(statistics.fmean(durations), 3),
        },
        "acceptance": {
            "p95_threshold_ms": threshold_ms,
            "passed": p95 <= threshold_ms and not failures and len(durations) == samples,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "not reported",
        },
        "limitations": [
            "This is process-local construction timing, not a container orchestration measurement.",
            "SQLite is in memory and the seed dataset is small and synthetic.",
            "The measurement excludes interpreter and operating-system process launch time.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Nightingale API cold construction")
    parser.add_argument("--samples", type=int, default=40)
    parser.add_argument("--threshold-ms", type=float, default=500.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "evidence" / "cold_start_benchmark.json",
    )
    args = parser.parse_args()
    if args.samples < 2:
        parser.error("--samples must be at least 2")
    result = benchmark(args.samples, args.threshold_ms)
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if result["acceptance"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
