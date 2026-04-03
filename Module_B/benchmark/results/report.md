# SQL Indexing Benchmark Report

## Response Time Comparison (ms)

| Endpoint | Before mean | After mean | Before p95 | After p95 | Δ p95 (ms) |
|----------|-------------|------------|------------|-----------|------------|
| `GET /admin/verify-audit` | 27.52 | 30.89 | 34.45 | 35.15 | -0.7 |
| `GET /api/members/1 [admin]` | 14.53 | 14.38 | 20.64 | 17.94 | +2.7 |
| `GET /api/teams/1 [admin]` | 13.75 | 13.86 | 17.86 | 17.73 | +0.13 |
| `GET /api/performance-logs [admin]` | 13.0 | 13.32 | 17.48 | 15.59 | +1.89 |
| `GET /api/members/1 [coach]` | 14.41 | 14.5 | 17.36 | 17.7 | -0.34 |

## SQL Execution Time Comparison (ms)

| Query | Before mean | After mean | Before p95 | After p95 | Δ p95 |
|-------|-------------|------------|------------|-----------|-------|
| `GET /admin/audit-log` | 1.168 | 1.104 | 1.752 | 1.674 | 0.078 |
| `GET /api/equipment/issues [admin]` | 0.567 | 0.589 | 0.866 | 1.101 | -0.235 |
| `GET /api/equipment/issues [player]` | 0.395 | 0.443 | 0.547 | 0.669 | -0.122 |
| `GET /api/events [admin]` | 0.665 | 0.665 | 1.096 | 1.002 | 0.094 |
| `GET /api/events?sport_id=1` | 0.511 | 0.482 | 0.787 | 0.842 | -0.055 |
| `GET /api/events?tournament_id=1` | 0.506 | 0.527 | 0.741 | 1.096 | -0.355 |
| `GET /api/medical-records/1 [admin]` | 0.394 | 0.379 | 0.579 | 0.597 | -0.018 |
| `GET /api/members [admin]` | 0.593 | 0.487 | 1.099 | 0.888 | 0.211 |
| `GET /api/members/1 [admin]` | 0.351 | 0.372 | 0.496 | 0.606 | -0.11 |
| `GET /api/performance-logs [admin]` | 0.537 | 0.571 | 0.773 | 0.857 | -0.084 |
| `GET /api/performance-logs [coach]` | 0.619 | 0.745 | 1.019 | 1.395 | -0.376 |
| `GET /api/performance-logs [player]` | 0.44 | 0.455 | 0.693 | 0.653 | 0.04 |
| `GET /api/teams [admin]` | 0.435 | 0.457 | 0.604 | 0.596 | 0.008 |

## EXPLAIN Access Plan Changes

### `GET /admin/audit-log`

**Before:**
```
  table=audit_log | type=index | possible_keys=None | key=PRIMARY | rows=100 | Extra=Backward index scan
```
**After:**
```
  table=audit_log | type=index | possible_keys=None | key=PRIMARY | rows=100 | Extra=Backward index scan
```

### `GET /api/equipment/issues [admin]`

**Before:**
```
  table=e | type=ALL | possible_keys=PRIMARY | key=None | rows=15 | Extra=Using temporary; Using filesort
  table=ei | type=ref | possible_keys=EquipmentID,MemberID | key=EquipmentID | rows=1 | Extra=None
  table=m | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```
**After:**
```
  table=e | type=ALL | possible_keys=PRIMARY | key=None | rows=15 | Extra=Using temporary; Using filesort
  table=ei | type=ref | possible_keys=EquipmentID,MemberID | key=EquipmentID | rows=1 | Extra=None
  table=m | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```

### `GET /api/equipment/issues [player]`

**Before:**
```
  table=m | type=const | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=Using filesort
  table=ei | type=ref | possible_keys=EquipmentID,MemberID | key=MemberID | rows=2 | Extra=None
  table=e | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```
**After:**
```
  table=m | type=const | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=Using filesort
  table=ei | type=ref | possible_keys=EquipmentID,MemberID | key=MemberID | rows=2 | Extra=None
  table=e | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```

### `GET /api/events [admin]`

**Before:**
```
  table=s | type=index | possible_keys=PRIMARY | key=SportName | rows=8 | Extra=Using index; Using temporary; Using filesort
  table=e | type=ref | possible_keys=VenueID,SportID | key=SportID | rows=1 | Extra=None
  table=v | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=t | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```
**After:**
```
  table=s | type=index | possible_keys=PRIMARY | key=SportName | rows=8 | Extra=Using index; Using temporary; Using filesort
  table=e | type=ref | possible_keys=VenueID,idx_event_sportid_eventdate | key=idx_event_sportid_eventdate | rows=1 | Extra=None
  table=v | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=t | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```

### `GET /api/events?sport_id=1`

**Before:**
```
  table=s | type=const | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=Using filesort
  table=e | type=ref | possible_keys=VenueID,SportID | key=SportID | rows=4 | Extra=None
  table=t | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=v | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```
**After:**
```
  table=s | type=const | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=e | type=ref | possible_keys=VenueID,idx_event_sportid_eventdate | key=idx_event_sportid_eventdate | rows=4 | Extra=None
  table=t | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=v | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```

### `GET /api/events?tournament_id=1`

**Before:**
```
  table=e | type=ref | possible_keys=TournamentID,VenueID,SportID | key=TournamentID | rows=3 | Extra=Using filesort
  table=t | type=const | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=s | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=v | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```
**After:**
```
  table=e | type=ref | possible_keys=TournamentID,VenueID,idx_event_sportid_eventdate | key=TournamentID | rows=3 | Extra=Using filesort
  table=t | type=const | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=s | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=v | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```

### `GET /api/medical-records/1 [admin]`

**Before:**
```
  table=MedicalRecord | type=ref | possible_keys=MemberID | key=MemberID | rows=2 | Extra=Using filesort
```
**After:**
```
  table=MedicalRecord | type=ref | possible_keys=idx_medical_member_date | key=idx_medical_member_date | rows=2 | Extra=None
```

### `GET /api/members [admin]`

**Before:**
```
  table=Member | type=index | possible_keys=None | key=PRIMARY | rows=20 | Extra=None
```
**After:**
```
  table=Member | type=index | possible_keys=None | key=PRIMARY | rows=20 | Extra=None
```

### `GET /api/members/1 [admin]`

**Before:**
```
  table=tm | type=ref | possible_keys=PRIMARY,MemberID | key=MemberID | rows=2 | Extra=None
  table=t | type=eq_ref | possible_keys=PRIMARY,SportID | key=PRIMARY | rows=1 | Extra=None
  table=s | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```
**After:**
```
  table=tm | type=ref | possible_keys=PRIMARY,idx_teammember_memberid | key=idx_teammember_memberid | rows=2 | Extra=None
  table=t | type=eq_ref | possible_keys=PRIMARY,SportID | key=PRIMARY | rows=1 | Extra=None
  table=s | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```

### `GET /api/performance-logs [admin]`

**Before:**
```
  table=pl | type=ALL | possible_keys=MemberID,SportID | key=None | rows=1 | Extra=Using filesort
  table=s | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=m | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```
**After:**
```
  table=pl | type=ALL | possible_keys=SportID,idx_perflog_member_date | key=None | rows=20 | Extra=Using filesort
  table=s | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=m | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```

### `GET /api/performance-logs [coach]`

**Before:**
```
  table=pl | type=ALL | possible_keys=MemberID,SportID | key=None | rows=1 | Extra=Using filesort
  table=s | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=m | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=tm | type=ref | possible_keys=PRIMARY,MemberID | key=MemberID | rows=1 | Extra=Using index
  table=t | type=eq_ref | possible_keys=PRIMARY,CoachID | key=PRIMARY | rows=1 | Extra=Using where; FirstMatch(m)
```
**After:**
```
  table=<subquery2> | type=ALL | possible_keys=None | key=None | rows=None | Extra=Using temporary; Using filesort
  table=pl | type=ref | possible_keys=SportID,idx_perflog_member_date | key=idx_perflog_member_date | rows=1 | Extra=None
  table=s | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=m | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=t | type=ref | possible_keys=PRIMARY,CoachID | key=CoachID | rows=4 | Extra=Using index
  table=tm | type=ref | possible_keys=PRIMARY,idx_teammember_memberid | key=PRIMARY | rows=1 | Extra=Using index
```

### `GET /api/performance-logs [player]`

**Before:**
```
  table=m | type=const | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=Using filesort
  table=pl | type=ref | possible_keys=MemberID,SportID | key=MemberID | rows=5 | Extra=None
  table=s | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```
**After:**
```
  table=m | type=const | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
  table=pl | type=ref | possible_keys=SportID,idx_perflog_member_date | key=idx_perflog_member_date | rows=5 | Extra=None
  table=s | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```

### `GET /api/teams [admin]`

**Before:**
```
  table=s | type=index | possible_keys=PRIMARY | key=SportName | rows=8 | Extra=Using index; Using temporary; Using filesort
  table=t | type=ref | possible_keys=SportID | key=SportID | rows=1 | Extra=None
  table=m | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```
**After:**
```
  table=s | type=index | possible_keys=PRIMARY | key=SportName | rows=8 | Extra=Using index; Using temporary; Using filesort
  table=t | type=ref | possible_keys=SportID | key=SportID | rows=1 | Extra=None
  table=m | type=eq_ref | possible_keys=PRIMARY | key=PRIMARY | rows=1 | Extra=None
```
