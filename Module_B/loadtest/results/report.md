# Load Test & Failure Simulation Report

**Generated:** 2026-04-04 00:10:53
**Total Duration:** 159.3s

## 1. Race Condition Tests

| Test | Passed | Details |
|------|--------|---------|
| RC-1: Equipment Issue Race | PASS | success_count=5, fail_count=15, db_issued=5 |
| RC-2: Tournament Registration Race | PASS | success_count=1, fail_count=9, db_count=1 |
| RC-3: Concurrent ID Generation | PASS | success_count=10, fail_count=10, duplicates=0 |

## 2. ACID Verification

| Property | Test | Passed | Details |
|----------|------|--------|---------|
| Atomicity | Atomicity: Cross-DB Member Creation | PASS | orphan=no |
| Consistency | Consistency: Invariant Checks | PASS | {'equipment_qty': True, 'no_dup_registrations': True, 'no_negatives': True} |
| Isolation | Isolation: No Dirty Reads | PASS | reads_before_commit=[10] |
| Isolation | Isolation: Valid States Only | PASS | success_count=8, final_available=2 |
| Durability | Durability: Committed Data Persistence | PASS |  |

## 3. Failure Simulation

| Test | Passed | Details |
|------|--------|---------|
| FS-1: Connection Kill | PASS | connections_killed=4, orphans=0 |
| FS-2: Pool Exhaustion | PASS | pool_errors=15, recovered=True |
| FS-3: Full Stack Restart Verification | PASS | issue_count=0 |

## 4. Stress Test

| Test | Passed | Requests | Failure Rate | Mean (ms) | p95 (ms) | RPS |
|------|--------|----------|--------------|-----------|----------|-----|
| ST-1: Automated Locust Stress Test | PASS | 5408 | 0.3% | 71.13 | 210.0 | 45.07 |

## 5. Database Consistency Report

| Check | Result |
|-------|--------|
| equipment_invariant | PASS |
| no_duplicate_registrations | PASS |
| no_duplicate_member_ids | PASS |
| cross_db_consistency | PASS |
| no_negative_quantities | PASS |
| no_orphan_members | PASS |

## 6. Requirement Mapping

| Assignment Requirement | Evidence | Result |
|------------------------|----------|--------|
| Concurrent usage safety | RC-1: Equipment Issue Race | PASS |
| Race condition testing | RC-2: Tournament Registration Race | PASS |
| Atomicity / rollback | Atomicity: Cross-DB Member Creation | PASS |
| Isolation | Isolation: No Dirty Reads | PASS |
| Durability after restart | FS-3: Full Stack Restart Verification | PASS |
| Stress testing under load | ST-1: Automated Locust Stress Test | PASS |

## Summary

- **Test Scenarios:** 12/12 passed
- **DB Checks:** 6/6 passed
- **Duration:** 159.3s