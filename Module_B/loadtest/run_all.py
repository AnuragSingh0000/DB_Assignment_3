"""Master orchestrator — runs all test suites and generates a report."""

import os
import sys
import time
from datetime import datetime

# Ensure loadtest/ is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_race_conditions import run_all as run_race_conditions
from test_acid import run_all as run_acid
from test_failure import run_all as run_failure
from verify import run_all_checks
from progress import ProgressBar


def generate_report(rc_results, acid_results, fail_results, verify_results, elapsed):
    """Generate a Markdown report in results/report.md."""
    lines = []
    lines.append("# Load Test & Failure Simulation Report")
    lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Total Duration:** {elapsed:.1f}s\n")

    # Race Conditions
    lines.append("## 1. Race Condition Tests\n")
    lines.append("| Test | Passed | Details |")
    lines.append("|------|--------|---------|")
    for r in rc_results:
        status = "PASS" if r.get("passed") else "FAIL"
        details = []
        if "success_count" in r:
            details.append(f"success={r['success_count']}")
        if "fail_count" in r:
            details.append(f"fail={r['fail_count']}")
        if "db_issued" in r:
            details.append(f"db_issued={r['db_issued']}")
        if "db_count" in r:
            details.append(f"db_count={r['db_count']}")
        if "duplicates" in r:
            details.append(f"duplicates={r['duplicates']}")
        if "error" in r:
            details.append(f"error: {r['error'][:50]}")
        lines.append(f"| {r.get('test', 'unknown')} | {status} | {', '.join(details)} |")

    # ACID Tests
    lines.append("\n## 2. ACID Verification\n")
    lines.append("| Property | Test | Passed | Details |")
    lines.append("|----------|------|--------|---------|")
    for r in acid_results:
        prop = r.get("test", "").split(":")[0] if ":" in r.get("test", "") else "ACID"
        status = "PASS" if r.get("passed") else "FAIL"
        details = []
        if "has_orphan" in r:
            details.append(f"orphan={'YES' if r['has_orphan'] else 'no'}")
        if "checks" in r:
            details.append(str(r["checks"]))
        if "reads_before_commit" in r:
            details.append(f"reads_before_commit={r['reads_before_commit']}")
        if "error" in r:
            details.append(f"error: {r['error'][:50]}")
        lines.append(f"| {prop} | {r.get('test', 'unknown')} | {status} | {', '.join(details)[:80]} |")

    # Failure Simulation
    lines.append("\n## 3. Failure Simulation\n")
    lines.append("| Test | Passed | Details |")
    lines.append("|------|--------|---------|")
    for r in fail_results:
        status = "PASS" if r.get("passed") else "FAIL"
        details = []
        if "connections_killed" in r:
            details.append(f"killed={r['connections_killed']}")
        if "orphans" in r:
            details.append(f"orphans={r['orphans']}")
        if "pool_errors" in r:
            details.append(f"pool_errors={r['pool_errors']}")
        if "recovered" in r:
            details.append(f"recovered={r['recovered']}")
        if "error" in r:
            details.append(f"error: {r['error'][:50]}")
        lines.append(f"| {r.get('test', 'unknown')} | {status} | {', '.join(details)} |")

    # DB Consistency
    lines.append("\n## 4. Database Consistency Report\n")
    lines.append("| Check | Result |")
    lines.append("|-------|--------|")
    for name, passed in verify_results.items():
        lines.append(f"| {name} | {'PASS' if passed else 'FAIL'} |")

    # Summary
    all_results = rc_results + acid_results + fail_results
    total = len(all_results)
    passed = sum(1 for r in all_results if r.get("passed"))
    lines.append(f"\n## Summary\n")
    lines.append(f"- **Test Scenarios:** {passed}/{total} passed")
    lines.append(f"- **DB Checks:** {sum(verify_results.values())}/{len(verify_results)} passed")
    lines.append(f"- **Duration:** {elapsed:.1f}s")

    report = "\n".join(lines)

    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(results_dir, exist_ok=True)
    report_path = os.path.join(results_dir, "report.md")
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\nReport written to: {report_path}")
    return report_path


def main():
    start = time.time()
    phase_progress = ProgressBar(4, "Overall progress")

    print("\n" + "=" * 70)
    print("  OLYMPIA TRACK — Load Testing & Failure Simulation Suite")
    print("=" * 70)

    # 1. Race conditions
    print("\n\n>>> PHASE 1: Race Condition Tests <<<")
    rc_results = run_race_conditions()
    phase_progress.advance(detail="race conditions complete")

    # 2. ACID tests
    print("\n\n>>> PHASE 2: ACID Property Tests <<<")
    acid_results = run_acid()
    phase_progress.advance(detail="ACID checks complete")

    # 3. Failure simulation
    print("\n\n>>> PHASE 3: Failure Simulation <<<")
    fail_results = run_failure()
    phase_progress.advance(detail="failure simulation complete")

    # 4. Post-test verification
    print("\n\n>>> PHASE 4: Post-Test Database Verification <<<")
    verify_results = run_all_checks()
    phase_progress.advance(detail="verification complete")
    phase_progress.finish(detail="suite complete")

    elapsed = time.time() - start

    # Generate report
    report_path = generate_report(rc_results, acid_results, fail_results, verify_results, elapsed)

    # Final summary
    all_results = rc_results + acid_results + fail_results
    total = len(all_results)
    passed = sum(1 for r in all_results if r.get("passed"))
    print(f"\n{'='*70}")
    print(f"  DONE — {passed}/{total} tests passed in {elapsed:.1f}s")
    print(f"{'='*70}\n")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
