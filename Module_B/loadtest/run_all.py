"""Master orchestrator — runs all test suites and generates a report."""

from __future__ import annotations

import importlib
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure loadtest/ is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as loadtest_config
from harness import ManagedHarness
from progress import ProgressBar


def _import_runtime_modules():
    modules = {}
    for name in (
        "test_race_conditions",
        "test_acid",
        "test_failure",
        "test_stress",
        "verify",
    ):
        modules[name] = importlib.import_module(name)
    return modules


def _requirement_rows(rc_results, acid_results, fail_results, stress_results, breaking_point_result):
    acid_by_name = {result.get("test"): result for result in acid_results}
    failure_by_name = {result.get("test"): result for result in fail_results}
    race_by_name = {result.get("test"): result for result in rc_results}
    all_profiles_passed = all(r.get("passed") for r in stress_results) if stress_results else False
    return [
        ("Concurrent usage safety", race_by_name.get("RC-1: Equipment Issue Race", {}).get("test"), race_by_name.get("RC-1: Equipment Issue Race", {}).get("passed")),
        ("Race condition testing", race_by_name.get("RC-2: Tournament Registration Race", {}).get("test"), race_by_name.get("RC-2: Tournament Registration Race", {}).get("passed")),
        ("Atomicity / rollback", acid_by_name.get("Atomicity: Cross-DB Member Creation", {}).get("test"), acid_by_name.get("Atomicity: Cross-DB Member Creation", {}).get("passed")),
        ("Isolation", acid_by_name.get("Isolation: No Dirty Reads", {}).get("test"), acid_by_name.get("Isolation: No Dirty Reads", {}).get("passed")),
        ("Durability after restart", failure_by_name.get("FS-3: Full Stack Restart Verification", {}).get("test"), failure_by_name.get("FS-3: Full Stack Restart Verification", {}).get("passed")),
        ("Stress testing under load", "ST-1: Load Profiles (Medium/Heavy/Spike)", all_profiles_passed),
        ("Breaking point analysis", breaking_point_result.get("test"), breaking_point_result.get("passed")),
    ]


def generate_report(rc_results, acid_results, fail_results, stress_results, breaking_point_result, verify_results, elapsed):
    """Generate a Markdown report in results/report.md."""
    lines = []
    lines.append("# Load Test & Failure Simulation Report")
    lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Total Duration:** {elapsed:.1f}s\n")

    lines.append("## 1. Race Condition Tests\n")
    lines.append("| Test | Passed | Details |")
    lines.append("|------|--------|---------|")
    for result in rc_results:
        status = "PASS" if result.get("passed") else "FAIL"
        details = []
        for key in ("success_count", "fail_count", "db_issued", "db_count", "duplicates"):
            if key in result:
                details.append(f"{key}={result[key]}")
        if "error" in result:
            details.append(f"error={result['error'][:80]}")
        lines.append(f"| {result.get('test', 'unknown')} | {status} | {', '.join(details)} |")

    lines.append("\n## 2. ACID Verification\n")
    lines.append("| Property | Test | Passed | Details |")
    lines.append("|----------|------|--------|---------|")
    for result in acid_results:
        prop = result.get("test", "").split(":")[0] if ":" in result.get("test", "") else "ACID"
        status = "PASS" if result.get("passed") else "FAIL"
        details = []
        if "has_orphan" in result:
            details.append(f"orphan={'YES' if result['has_orphan'] else 'no'}")
        if "checks" in result:
            details.append(str(result["checks"]))
        if "reads_before_commit" in result:
            details.append(f"reads_before_commit={result['reads_before_commit']}")
        if "success_count" in result:
            details.append(f"success_count={result['success_count']}")
        if "final_available" in result:
            details.append(f"final_available={result['final_available']}")
        if "error" in result:
            details.append(f"error={result['error'][:80]}")
        lines.append(f"| {prop} | {result.get('test', 'unknown')} | {status} | {', '.join(details)[:120]} |")

    lines.append("\n## 3. Failure Simulation\n")
    lines.append("| Test | Passed | Details |")
    lines.append("|------|--------|---------|")
    for result in fail_results:
        status = "PASS" if result.get("passed") else "FAIL"
        details = []
        for key in ("connections_killed", "orphans", "pool_errors", "recovered", "issue_count"):
            if key in result:
                details.append(f"{key}={result[key]}")
        if "error" in result:
            details.append(f"error={result['error'][:80]}")
        lines.append(f"| {result.get('test', 'unknown')} | {status} | {', '.join(details)} |")

    # --- Section 4: Load Profiles ---
    lines.append("\n## 4. Stress Test — Load Profiles\n")
    lines.append("| Profile | Passed | Requests | Failure Rate | Mean (ms) | p95 (ms) | RPS |")
    lines.append("|---------|--------|----------|--------------|-----------|----------|-----|")
    for sr in stress_results:
        lines.append(
            "| {profile} | {status} | {requests} | {failure_rate}% | {mean} | {p95} | {rps} |".format(
                profile=sr.get("profile", "unknown"),
                status="PASS" if sr.get("passed") else "FAIL",
                requests=sr.get("total_requests", "-"),
                failure_rate=sr.get("failure_rate", "-"),
                mean=sr.get("mean_response_ms", "-"),
                p95=sr.get("p95_ms", "-"),
                rps=sr.get("requests_per_sec", "-"),
            )
        )

    # --- Section 4b: Breaking point ramp ---
    lines.append("\n### Ramp to Breaking Point (ST-2)\n")
    bp = breaking_point_result.get("breaking_point")
    lines.append(f"**Breaking point:** {bp if bp else 'Not reached (system sustained max load)'}")
    lines.append(f"**Max sustained users:** {breaking_point_result.get('max_sustained', '-')}\n")
    lines.append("| Users | Status | Failure Rate | p95 (ms) | RPS |")
    lines.append("|-------|--------|--------------|----------|-----|")
    for step in breaking_point_result.get("steps", []):
        lines.append(
            "| {users} | {status} | {failure_rate}% | {p95} | {rps} |".format(
                users=step.get("users", "-"),
                status=step.get("status", "-"),
                failure_rate=step.get("failure_rate", "-"),
                p95=step.get("p95_ms", "-"),
                rps=step.get("requests_per_sec", "-"),
            )
        )

    lines.append("\n## 5. Database Consistency Report\n")
    lines.append("| Check | Result |")
    lines.append("|-------|--------|")
    for name, passed in verify_results.items():
        lines.append(f"| {name} | {'PASS' if passed else 'FAIL'} |")

    lines.append("\n## 6. Requirement Mapping\n")
    lines.append("| Assignment Requirement | Evidence | Result |")
    lines.append("|------------------------|----------|--------|")
    for requirement, evidence, passed in _requirement_rows(rc_results, acid_results, fail_results, stress_results, breaking_point_result):
        lines.append(f"| {requirement} | {evidence or 'N/A'} | {'PASS' if passed else 'FAIL'} |")

    all_results = rc_results + acid_results + fail_results + stress_results + [breaking_point_result]
    total = len(all_results)
    passed = sum(1 for result in all_results if result.get("passed"))
    lines.append(f"\n## Summary\n")
    lines.append(f"- **Test Scenarios:** {passed}/{total} passed")
    lines.append(f"- **DB Checks:** {sum(verify_results.values())}/{len(verify_results)} passed")
    lines.append(f"- **Duration:** {elapsed:.1f}s")

    report = "\n".join(lines)
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    report_path = results_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport written to: {report_path}")
    return report_path


def main():
    start = time.time()
    phase_progress = ProgressBar(5, "Overall progress")
    module_b_dir = Path(__file__).resolve().parents[1]

    print("\n" + "=" * 70)
    print("  OLYMPIA TRACK — Load Testing & Failure Simulation Suite")
    print("=" * 70)

    normal_pool_size = loadtest_config.DB_POOL_SIZE
    with ManagedHarness(module_b_dir, port=loadtest_config.TEST_API_PORT, pool_size=normal_pool_size) as harness:
        os.environ["TEST_BASE_URL"] = harness.base_url
        loadtest_config.BASE_URL = harness.base_url
        loadtest_config.DB_POOL_SIZE = normal_pool_size
        modules = _import_runtime_modules()

        print("\n\n>>> PHASE 1: Race Condition Tests <<<")
        rc_results = modules["test_race_conditions"].run_all()
        phase_progress.advance(detail="race conditions complete")

        print("\n\n>>> PHASE 2: ACID Property Tests <<<")
        acid_results = modules["test_acid"].run_all()
        phase_progress.advance(detail="ACID checks complete")

        failure_pool_size = loadtest_config.FAILURE_DB_POOL_SIZE
        harness.pool_size = failure_pool_size
        loadtest_config.DB_POOL_SIZE = failure_pool_size
        harness.restart_api()
        modules["test_failure"] = importlib.reload(modules["test_failure"])
        modules["test_stress"] = importlib.reload(modules["test_stress"])

        print("\n\n>>> PHASE 3: Failure Simulation <<<")
        fail_results = modules["test_failure"].run_all()
        phase_progress.advance(detail="failure simulation complete")

        harness.pool_size = normal_pool_size
        loadtest_config.DB_POOL_SIZE = normal_pool_size
        harness.restart_api()
        modules["test_stress"] = importlib.reload(modules["test_stress"])

        print("\n\n>>> PHASE 4: Stress Test (Load Profiles + Breaking Point) <<<")
        stress_results = modules["test_stress"].run_stress_test()
        breaking_point_result = modules["test_stress"].run_breaking_point_test()
        phase_progress.advance(detail="stress test complete")

        print("\n\n>>> PHASE 5: Post-Test Database Verification <<<")
        verify_results = modules["verify"].run_all_checks()
        phase_progress.advance(detail="verification complete")
        phase_progress.finish(detail="suite complete")

    elapsed = time.time() - start
    generate_report(rc_results, acid_results, fail_results, stress_results, breaking_point_result, verify_results, elapsed)

    all_results = rc_results + acid_results + fail_results + stress_results + [breaking_point_result]
    total = len(all_results)
    passed = sum(1 for result in all_results if result.get("passed"))
    print(f"\n{'='*70}")
    print(f"  DONE — {passed}/{total} tests passed in {elapsed:.1f}s")
    print(f"{'='*70}\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
