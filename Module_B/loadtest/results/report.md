# Load Test & Failure Simulation Report

**Generated:** 2026-04-03 23:30:54
**Total Duration:** 11.8s

## 1. Race Condition Tests

| Test | Passed | Details |
|------|--------|---------|
| RC-1: Equipment Issue Race | PASS | success=5, fail=15, db_issued=5 |
| RC-2: Tournament Registration Race | PASS | success=1, fail=9, db_count=1 |
| RC-3: Concurrent ID Generation | PASS | success=20, fail=0, duplicates=0 |

## 2. ACID Verification

| Property | Test | Passed | Details |
|----------|------|--------|---------|
| Atomicity | Atomicity: Cross-DB Member Creation | PASS | orphan=no |
| Consistency | Consistency: Invariant Checks | PASS | {'equipment_qty': True, 'no_dup_registrations': True, 'no_negatives': True} |
| Isolation | Isolation: No Dirty Reads | PASS | reads_before_commit=[10] |
| Isolation | Isolation: Valid States Only | PASS |  |
| Durability | Durability: Committed Data Persistence | PASS |  |

## 3. Failure Simulation

| Test | Passed | Details |
|------|--------|---------|
| FS-1: Connection Kill | PASS | killed=15, orphans=0 |
| FS-2: Pool Exhaustion | PASS | pool_errors=0, recovered=True |
| FS-3: Server Crash Simulation | PASS |  |

## 4. Database Consistency Report

| Check | Result |
|-------|--------|
| equipment_invariant | PASS |
| no_duplicate_registrations | PASS |
| no_duplicate_member_ids | PASS |
| cross_db_consistency | PASS |
| no_negative_quantities | PASS |
| no_orphan_members | PASS |

## Summary

- **Test Scenarios:** 11/11 passed
- **DB Checks:** 6/6 passed
- **Duration:** 11.8s