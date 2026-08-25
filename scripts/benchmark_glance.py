#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx2 as httpx


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot calculate a percentile without observations")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def benchmark(
    *,
    base_url: str,
    samples: int,
    warmups: int,
    timeout: float,
    threshold_ms: float,
) -> dict:
    path = "/api/v1/patients/patient-maya-chen/glance"
    headers = {"X-Demo-User": "user-clinician-lina"}
    durations: list[float] = []
    failures: list[dict] = []
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        health = client.get("/health")
        health.raise_for_status()
        for _ in range(warmups):
            response = client.get(path, headers=headers)
            response.raise_for_status()
        for index in range(samples):
            started = time.perf_counter_ns()
            try:
                response = client.get(path, headers=headers)
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                if response.status_code != 200:
                    failures.append({"sample": index, "status": response.status_code})
                else:
                    payload = response.json()
                    if not payload.get("groups"):
                        failures.append({"sample": index, "status": "missing_groups"})
                    durations.append(elapsed_ms)
            except Exception as exc:  # noqa: BLE001 - evidence must retain any failure class
                failures.append({"sample": index, "status": type(exc).__name__})

    if not durations:
        raise RuntimeError("Benchmark produced no successful observations")
    p95 = percentile(durations, 0.95)
    result = {
        "measurement": "Warm-path end-to-end HTTP latency from local client to local Uvicorn API",
        "endpoint": path,
        "base_url": base_url,
        "recorded_at": datetime.now(UTC).isoformat(),
        "warmups": warmups,
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
            "passed": p95 <= threshold_ms and not failures,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "not reported",
        },
        "limitations": [
            "Local loopback is an approximation, not a production network measurement.",
            "The read path uses seeded synthetic data and a precomputed glance projection.",
            "No LLM call occurs on the glance read path by design.",
        ],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the Nightingale glance read path")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--samples", type=int, default=600)
    parser.add_argument("--warmups", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--threshold-ms", type=float, default=300.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = benchmark(
        base_url=args.base_url,
        samples=args.samples,
        warmups=args.warmups,
        timeout=args.timeout,
        threshold_ms=args.threshold_ms,
    )
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if result["acceptance"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
