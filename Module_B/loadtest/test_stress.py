"""Bounded Locust stress test with machine-readable metrics."""

from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path

from config import (
    BASE_URL,
    LOCUST_DURATION,
    LOCUST_MAX_FAILURE_RATE,
    LOCUST_MAX_P95_MS,
    LOCUST_SPAWN_RATE,
    LOCUST_USERS,
)


def _banner(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


def _duration_seconds(duration: str) -> float:
    total = 0
    current = ""
    units = {"s": 1, "m": 60, "h": 3600}
    for ch in duration.strip():
        if ch.isdigit() or ch == ".":
            current += ch
            continue
        if ch not in units or not current:
            raise ValueError(f"Unsupported duration string: {duration}")
        total += float(current) * units[ch]
        current = ""
    if current:
        total += float(current)
    return total


def _aggregate_p95(histogram: dict[float, int], total_requests: int) -> float:
    if total_requests <= 0:
        return 0.0
    threshold = math.ceil(total_requests * 0.95)
    running = 0
    for latency in sorted(histogram):
        running += histogram[latency]
        if running >= threshold:
            return latency
    return max(histogram, default=0.0)


def run_stress_test():
    _banner("ST-1: Automated Locust Stress Test")
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    csv_prefix = results_dir / "locust"
    html_report = results_dir / "locust_report.html"
    cmd = [
        "../.venv/bin/python",
        "-m",
        "locust",
        "-f",
        "loadtest/locustfile.py",
        "--headless",
        "-u",
        str(LOCUST_USERS),
        "-r",
        str(LOCUST_SPAWN_RATE),
        "-t",
        LOCUST_DURATION,
        "--host",
        BASE_URL,
        "--only-summary",
        "--json",
        "--skip-log-setup",
        "--exit-code-on-error",
        "0",
        "--csv",
        str(csv_prefix),
        "--html",
        str(html_report),
    ]
    print(
        f"  Running Locust against {BASE_URL} "
        f"(users={LOCUST_USERS}, spawn_rate={LOCUST_SPAWN_RATE}, duration={LOCUST_DURATION})..."
    )
    proc = subprocess.run(
        cmd,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONWARNINGS": "ignore::DeprecationWarning"},
        timeout=int(_duration_seconds(LOCUST_DURATION) + 90),
    )
    if proc.returncode != 0:
        print(f"  [FAIL] Locust command failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return {
            "test": "ST-1: Automated Locust Stress Test",
            "passed": False,
            "error": proc.stderr.strip() or proc.stdout.strip(),
        }
    try:
        stats = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {
            "test": "ST-1: Automated Locust Stress Test",
            "passed": False,
            "error": f"Could not parse Locust JSON output: {exc}",
        }
    total_requests = 0
    total_failures = 0
    total_response_time = 0.0
    histogram: dict[float, int] = {}
    for row in stats:
        total_requests += row.get("num_requests", 0)
        total_failures += row.get("num_failures", 0)
        total_response_time += row.get("total_response_time", 0.0)
        for latency, count in row.get("response_times", {}).items():
            histogram[float(latency)] = histogram.get(float(latency), 0) + count
    duration_seconds = _duration_seconds(LOCUST_DURATION)
    failure_rate = (100.0 * total_failures / total_requests) if total_requests else 0.0
    mean_response_ms = (total_response_time / total_requests) if total_requests else 0.0
    p95_ms = _aggregate_p95(histogram, total_requests)
    requests_per_sec = (total_requests / duration_seconds) if duration_seconds else 0.0
    passed = failure_rate <= LOCUST_MAX_FAILURE_RATE and p95_ms <= LOCUST_MAX_P95_MS
    print(
        "  Metrics: "
        f"requests={total_requests}, failure_rate={failure_rate:.2f}%, "
        f"mean={mean_response_ms:.2f}ms, p95={p95_ms:.2f}ms, rps={requests_per_sec:.2f}"
    )
    print(
        f"  Thresholds: failure_rate<={LOCUST_MAX_FAILURE_RATE:.2f}%, "
        f"p95<={LOCUST_MAX_P95_MS:.2f}ms"
    )
    print(f"  [{'PASS' if passed else 'FAIL'}] ST-1: Automated Locust Stress Test")
    return {
        "test": "ST-1: Automated Locust Stress Test",
        "passed": passed,
        "total_requests": total_requests,
        "failure_rate": round(failure_rate, 2),
        "mean_response_ms": round(mean_response_ms, 2),
        "p95_ms": round(p95_ms, 2),
        "requests_per_sec": round(requests_per_sec, 2),
        "html_report": str(html_report),
    }
