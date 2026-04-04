# Load Test & Failure Simulation Report

**Generated:** 2026-04-04 18:01:09
**Total Duration:** 888.3s

## 1. Race Condition Tests

| Test | Passed | Details |
|------|--------|---------|
| RC-1: Equipment Issue Race | PASS | success_count=5, fail_count=15, db_issued=5 |
| RC-2: Tournament Registration Race | PASS | success_count=1, fail_count=9, db_count=1 |
| RC-3: Concurrent ID Generation | PASS | success_count=20, fail_count=0, duplicates=0 |

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

## 4. Stress Test — Load Profiles

| Profile | Passed | Requests | Failure Rate | Mean (ms) | p95 (ms) | RPS |
|---------|--------|----------|--------------|-----------|----------|-----|
| Medium | PASS | 7357 | 0.0% | 37.29 | 87.0 | 24.52 |
| Heavy | PASS | 14641 | 2.17% | 92.97 | 270.0 | 48.8 |
| Spike | PASS | 3719 | 12.58% | 145.04 | 940.0 | 30.99 |

### Ramp to Breaking Point (ST-2)

**Breaking point:** 200
**Max sustained users:** 200

| Users | Status | Failure Rate | p95 (ms) | RPS |
|-------|--------|--------------|----------|-----|
| 50 | ok | 3.44% | 640.0 | 17.47 |
| 100 | ok | 11.17% | 730.0 | 20.3 |
| 150 | ok | 15.9% | 740.0 | 24.73 |
| 200 | breaking_point | 21.03% | 730.0 | 26.63 |

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
| Stress testing under load | ST-1: Load Profiles (Medium/Heavy/Spike) | PASS |
| Breaking point analysis | ST-2: Ramp to Breaking Point | PASS |

## Summary

- **Test Scenarios:** 15/15 passed
- **DB Checks:** 6/6 passed
- **Duration:** 888.3s