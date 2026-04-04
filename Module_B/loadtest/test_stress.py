"""Bounded Locust stress test with machine-readable metrics."""

from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path

from config import (
    BASE_URL,
    LOAD_PROFILES,
    STRESS_FAILURE_THRESHOLD,
    STRESS_MAX_USERS,
    STRESS_P95_THRESHOLD,
    STRESS_STEP_DURATION,
    STRESS_STEP_USERS,
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


def _run_locust(
    *,
    users: int,
    spawn_rate: int,
    duration: str,
    csv_prefix: Path,
    html_report: Path,
) -> dict:
    """Run a single Locust session and return parsed metrics."""
    cmd = [
        "../.venv/bin/python",
        "-m",
        "locust",
        "-f",
        "loadtest/locustfile.py",
        "--headless",
        "-u",
        str(users),
        "-r",
        str(spawn_rate),
        "-t",
        duration,
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
        f"(users={users}, spawn_rate={spawn_rate}, duration={duration})..."
    )
    proc = subprocess.run(
        cmd,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONWARNINGS": "ignore::DeprecationWarning"},
        timeout=int(_duration_seconds(duration) + 90),
    )
    if proc.returncode != 0:
        return {
            "passed": False,
            "error": proc.stderr.strip() or proc.stdout.strip(),
        }
    try:
        stats = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {
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

    duration_seconds = _duration_seconds(duration)
    failure_rate = (100.0 * total_failures / total_requests) if total_requests else 0.0
    mean_response_ms = (total_response_time / total_requests) if total_requests else 0.0
    p95_ms = _aggregate_p95(histogram, total_requests)
    requests_per_sec = (total_requests / duration_seconds) if duration_seconds else 0.0

    return {
        "total_requests": total_requests,
        "failure_rate": round(failure_rate, 2),
        "mean_response_ms": round(mean_response_ms, 2),
        "p95_ms": round(p95_ms, 2),
        "requests_per_sec": round(requests_per_sec, 2),
        "html_report": str(html_report),
    }


# ------------------------------------------------------------------
# ST-1: Multi-profile load test
# ------------------------------------------------------------------

def run_stress_test() -> list[dict]:
    """Run all load profiles and return a list of per-profile results."""
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    all_results: list[dict] = []

    for profile in LOAD_PROFILES:
        name = profile["name"]
        _banner(f"ST-1 [{name}]: Load Profile Test")
        tag = name.lower()
        csv_prefix = results_dir / f"locust_{tag}"
        html_report = results_dir / f"locust_report_{tag}.html"

        metrics = _run_locust(
            users=profile["users"],
            spawn_rate=profile["spawn_rate"],
            duration=profile["duration"],
            csv_prefix=csv_prefix,
            html_report=html_report,
        )

        max_fail = profile["max_failure_rate"]
        max_p95 = profile["max_p95_ms"]

        if "error" in metrics:
            passed = False
        else:
            passed = (
                metrics["failure_rate"] <= max_fail
                and metrics["p95_ms"] <= max_p95
            )

        result = {
            "test": f"ST-1 [{name}]: Load Profile Test",
            "profile": name,
            "passed": passed,
            **{k: v for k, v in metrics.items() if k not in ("passed",)},
        }

        if "error" not in metrics:
            print(
                f"  Metrics: "
                f"requests={metrics['total_requests']}, "
                f"failure_rate={metrics['failure_rate']:.2f}%, "
                f"mean={metrics['mean_response_ms']:.2f}ms, "
                f"p95={metrics['p95_ms']:.2f}ms, "
                f"rps={metrics['requests_per_sec']:.2f}"
            )
            print(
                f"  Thresholds: failure_rate<={max_fail:.2f}%, "
                f"p95<={max_p95:.2f}ms"
            )
        print(f"  [{'PASS' if passed else 'FAIL'}] ST-1 [{name}]")
        all_results.append(result)

    return all_results


# ------------------------------------------------------------------
# ST-2: Ramp to breaking point
# ------------------------------------------------------------------

def run_breaking_point_test() -> dict:
    """Progressively ramp users until the system breaks or max is reached."""
    _banner("ST-2: Ramp to Breaking Point")
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    steps: list[dict] = []
    current_users = STRESS_STEP_USERS
    breaking_point: int | None = None

    while current_users <= STRESS_MAX_USERS:
        print(f"\n  --- Step: {current_users} users for {STRESS_STEP_DURATION} ---")
        tag = f"ramp_{current_users}"
        csv_prefix = results_dir / f"locust_{tag}"
        html_report = results_dir / f"locust_report_{tag}.html"

        metrics = _run_locust(
            users=current_users,
            spawn_rate=current_users,
            duration=STRESS_STEP_DURATION,
            csv_prefix=csv_prefix,
            html_report=html_report,
        )

        step_info = {"users": current_users, **metrics}

        if "error" in metrics:
            print(f"  [BROKE] Locust errored at {current_users} users")
            step_info["status"] = "error"
            steps.append(step_info)
            breaking_point = current_users
            break

        print(
            f"  Metrics: failure_rate={metrics['failure_rate']:.2f}%, "
            f"p95={metrics['p95_ms']:.2f}ms, rps={metrics['requests_per_sec']:.2f}"
        )

        exceeded_failure = metrics["failure_rate"] > STRESS_FAILURE_THRESHOLD
        exceeded_p95 = metrics["p95_ms"] > STRESS_P95_THRESHOLD

        if exceeded_failure or exceeded_p95:
            reasons = []
            if exceeded_failure:
                reasons.append(f"failure_rate {metrics['failure_rate']:.2f}% > {STRESS_FAILURE_THRESHOLD}%")
            if exceeded_p95:
                reasons.append(f"p95 {metrics['p95_ms']:.2f}ms > {STRESS_P95_THRESHOLD}ms")
            print(f"  [BROKE] Breaking point at {current_users} users: {', '.join(reasons)}")
            step_info["status"] = "breaking_point"
            steps.append(step_info)
            breaking_point = current_users
            break

        step_info["status"] = "ok"
        steps.append(step_info)
        current_users += STRESS_STEP_USERS

    if breaking_point is None:
        print(f"  System sustained all steps up to {STRESS_MAX_USERS} users without breaking.")

    result = {
        "test": "ST-2: Ramp to Breaking Point",
        "passed": True,  # observational — finding the limit IS the result
        "breaking_point": breaking_point,
        "max_sustained": steps[-1]["users"] if steps else 0,
        "steps": steps,
    }
    print(f"  Breaking point: {breaking_point or 'not reached (max sustained)'}")
    print(f"  [DONE] ST-2: Ramp to Breaking Point")
    return result
