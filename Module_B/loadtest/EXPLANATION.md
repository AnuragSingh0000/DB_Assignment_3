# Module B: Load Testing & Failure Simulation — Detailed Explanation

> This document explains **everything** we built, **why** we built it, and **what each piece of code actually does** — written for someone who has never done stress testing or concurrency testing before.

---

## Table of Contents

1. [What is This Assignment About?](#1-what-is-this-assignment-about)
2. [Background Concepts You Need to Know](#2-background-concepts-you-need-to-know)
3. [The Application We're Testing](#3-the-application-were-testing)
4. [Bugs and Weaknesses We Found in the Code](#4-bugs-and-weaknesses-we-found-in-the-code)
5. [Directory Structure — What Each File Does](#5-directory-structure--what-each-file-does)
6. [Foundation Files — The Plumbing](#6-foundation-files--the-plumbing)
7. [Race Condition Tests — Explained Step by Step](#7-race-condition-tests--explained-step-by-step)
8. [ACID Property Tests — Explained Step by Step](#8-acid-property-tests--explained-step-by-step)
9. [Failure Simulation Tests — Explained Step by Step](#9-failure-simulation-tests--explained-step-by-step)
10. [Locust Stress Tests — Explained Step by Step](#10-locust-stress-tests--explained-step-by-step)
11. [The Bug Fixes We Made](#11-the-bug-fixes-we-made)
12. [The Verification System](#12-the-verification-system)
13. [How to Run Everything](#13-how-to-run-everything)
14. [What to Show in Your Video Demo](#14-what-to-show-in-your-video-demo)

---

## 1. What is This Assignment About?

The goal of Module B is to prove that our Olympia Track FastAPI application **behaves correctly** when:

- **Many users hit it at the same time** (concurrency / race conditions)
- **The database guarantees work properly** (ACID properties)
- **Things go wrong** (connections die, servers crash, resources run out)
- **Hundreds of users are active simultaneously** (stress/load testing)

In the real world, a web app doesn't serve one user at a time. Imagine 200 coaches all trying to issue equipment at the exact same moment. Will the database get corrupted? Will someone get equipment that doesn't exist? These tests answer that.

---

## 2. Background Concepts You Need to Know

### What is a Race Condition?

A **race condition** happens when two or more operations try to read/write the same data at the same time, and the final result depends on **who gets there first** — the "race."

**Real-world analogy:** Imagine a store has 5 balls on the shelf. Two customers reach for the last ball at the exact same time. Without proper coordination, both might think they got it — but there's only one ball. In databases, this is solved with **locks**.

### What is ACID?

ACID is a set of four guarantees that databases provide to keep your data safe:

| Property | What it means | Simple analogy |
|----------|--------------|----------------|
| **Atomicity** | An operation either **fully completes** or **fully rolls back**. No halfway states. | A bank transfer: either BOTH the debit AND credit happen, or NEITHER happens. You never lose money into thin air. |
| **Consistency** | The database always moves from one **valid state** to another. Rules (like "issued quantity can't exceed total") are never broken. | A chess game: every move must leave the board in a legal position. |
| **Isolation** | Concurrent transactions don't **see each other's uncommitted work**. | Two cashiers at separate registers don't see each other's half-processed transactions. |
| **Durability** | Once data is committed, it **survives crashes**. Even if you pull the power plug, committed data is safe. | Writing in permanent marker vs. pencil — once committed, it's permanent. |

### What is a Connection Pool?

Opening a database connection is expensive (like dialing a phone number). A **connection pool** keeps a fixed number of connections open and reuses them. In the current code, the app uses **32 pooled connections per database** (`olympia_auth` and `olympia_track`). If enough requests arrive at once, later requests still have to wait for a free connection or fail under pressure.

### What is Locust?

**Locust** is a Python tool for load/stress testing. It simulates hundreds of virtual users hitting your API simultaneously and measures how the server handles the load (response times, error rates, requests per second).

### What is a Thread?

A **thread** is a lightweight unit of execution. When we say "20 threads," think of 20 people all pressing the "Submit" button at the exact same millisecond. Python's `ThreadPoolExecutor` lets us launch many threads at once.

### What is FOR UPDATE?

`SELECT ... FOR UPDATE` is a MySQL command that says: "I'm reading this row, and I'm going to change it soon, so **lock it** — don't let anyone else touch it until I'm done." This prevents race conditions.

---

## 3. The Application We're Testing

**Olympia Track** is a sports management system with:

- **Two MySQL databases:**
  - `olympia_auth` — users, sessions, audit logs
  - `olympia_track` — members, teams, equipment, tournaments, events, etc.

- **Three user roles** (like permission levels):
  - **Admin** — can do everything
  - **Coach** — can manage their teams, issue equipment to their players
  - **Player** — can only view their own data

- **Key API endpoints we test:**
  - `POST /api/equipment/issue` — Coach issues equipment to a player (the main race condition target)
  - `POST /api/registrations/tournament/{id}/team/{id}` — Register a team for a tournament
  - `POST /api/members` — Create a new member (writes to BOTH databases)

- **Authentication:** JWT tokens stored in HTTP-only cookies. You log in, get a cookie, and every subsequent request includes that cookie automatically.

- **Tamper-detection triggers:** Normal API writes are supposed to set a special `@api_context` session variable so MySQL can distinguish "real API traffic" from suspicious direct SQL writes.

- **Connection pool:** The current code uses 32 pooled connections per database. Our failure tests still deliberately oversubscribe the system to study contention, recovery, and graceful degradation.

---

## 4. Bugs and Weaknesses We Found in the Code

Before writing tests, we audited the application code and found these issues:

### Bug 1: Atomicity Violation in Member Creation (CRITICAL)

**File:** `app/routers/members.py`, lines 305-310

**The problem:** When creating a member, the app does TWO inserts:
1. Insert a `Member` row into `olympia_track` 
2. Insert a `users` row into `olympia_auth`

These use a **single cross-database connection** (`get_cross_db()`) so they should be atomic (both succeed or both fail). But look at the original code:

```python
# Step 1: Insert Member row — this SUCCEEDS
member_id = insert_with_generated_id(...)  # Inserts into olympia_track.Member

# Step 2: Insert users row — this FAILS (e.g., duplicate username)
try:
    cross_db.execute("INSERT INTO users ...")
except Exception as e:
    # BUG: This RETURNS instead of RAISING
    return {"success": False, "message": humanize_db_error(e), "data": body}
    #      ^^^^^^ This is the problem!
```

**Why is `return` a bug?** The `get_cross_db()` dependency in `database.py` works like this:

```python
def get_cross_db():
    conn = mysql.connector.connect(...)
    cursor = conn.cursor()
    try:
        yield cursor        # <-- Your route code runs here
        conn.commit()        # <-- If no exception, COMMIT everything
    except Exception:
        conn.rollback()      # <-- If exception, ROLLBACK everything
```

When the code does `return` instead of `raise`, Python doesn't see an exception. So `get_cross_db()` calls `conn.commit()` — permanently saving the Member row even though the users row failed. **Result: an orphaned Member with no login account.**

**Our fix:** Changed `return` to `raise HTTPException(...)`. Now when the users INSERT fails, an exception propagates, `get_cross_db()` triggers rollback, and the Member row is also removed. Atomicity preserved.

### Bug 2: Missing API Context Secret Caused a Hidden Audit Storm

**Files:** `app/database.py`, `.env`, `.env.example`

The schema includes tamper-detection triggers. They are meant to fire only when someone writes directly to MySQL without going through the API. But during debugging we discovered that `API_CONTEXT_SECRET` was missing, so the app never correctly marked its own writes as API-originated.

That meant a normal API write could silently trigger extra database work:
1. The real INSERT/UPDATE from the API
2. A trigger firing because MySQL thought it was direct DB access
3. An extra insert into `direct_modification_log`
4. Another extra insert into `audit_log`

Under concurrency this created a hidden audit bottleneck. Requests started backing up on `audit_log`, and once enough piled up, unrelated endpoints like `/auth/login` and `/auth/isAuth` also began failing or timing out.

**Our fix:** Add `API_CONTEXT_SECRET` to the env files and make the app fail fast on startup if it is missing.

### Bug 3: ID Generation Used a Stale Transaction Snapshot

**File:** `app/services/id_generation.py`

The app was using `SELECT MAX(ID) + 1`, which is already a fragile pattern under concurrency. But the deeper issue was that this query was being run on the same long-lived transaction as the business logic.

That matters because waiting requests could keep seeing an old snapshot of the table:
1. Request A locks rows and inserts a new record
2. Request B waits
3. Request A commits
4. Request B finally wakes up, but its current transaction can still re-read an old `MAX(ID)`
5. Request B retries the same primary key and collides again

This is why we saw duplicate-key errors and timeouts in places that should have serialized cleanly.

**Our fix:** Keep the named MySQL lock, but read the next ID on a short dedicated autocommit connection so each retry sees the latest committed value.

### Weakness 4: Registration Uses Check-Then-Insert Without Locks

**File:** `app/routers/registration.py`, lines 31-36

```python
# Step 1: Check if already registered
track_db.execute("SELECT RegID FROM TournamentRegistration WHERE ...")
if track_db.fetchone():
    raise HTTPException(409, "Already registered")

# Step 2: Insert registration
insert_with_generated_id(...)
```

Between Step 1 and Step 2, another thread could also pass Step 1 (because neither has inserted yet). This is the classic **TOCTOU** (Time-Of-Check-to-Time-Of-Use) race. The app relies on a **UNIQUE constraint** on `(TournamentID, TeamID)` as a safety net — the second insert will fail with a duplicate key error. Our test verifies this safety net works.

### Strength: Equipment Issue Uses FOR UPDATE (Correct!)

**File:** `app/routers/equipment.py`, lines 322-331

```sql
SELECT e.TotalQuantity, COALESCE(SUM(ei.Quantity), 0) AS issued
FROM Equipment e
LEFT JOIN EquipmentIssue ei ON ...
WHERE e.EquipmentID = %s
GROUP BY e.TotalQuantity
FOR UPDATE                          -- <-- This lock is the hero
```

The `FOR UPDATE` lock means: "While I'm checking how much equipment is available, **nobody else can modify these rows**." This correctly serializes concurrent equipment issues. Our test proves it works — exactly 5 out of 20 threads succeed when there are 5 items available.

---

## 5. Directory Structure — What Each File Does

```
Module_B/loadtest/
|
|-- config.py                  # Settings: URLs, passwords, DB connection info
|-- helpers.py                 # Reusable functions: login, create test data, DB access
|-- verify.py                  # 6 database integrity checks (run after tests)
|
|-- test_race_conditions.py    # 3 tests: equipment race, registration race, ID race
|-- test_acid.py               # 5 tests: atomicity, consistency, isolation (x2), durability
|-- test_failure.py            # 3 tests: connection kill, pool exhaustion, crash sim
|-- locustfile.py              # Stress test: simulates Admin/Coach/Player traffic
|
|-- run_all.py                 # Runs everything in order, generates report.md
|-- results/                   # Output directory for the report
```

---

## 6. Foundation Files — The Plumbing

### config.py — Central Configuration

This file stores all the settings in one place so every other file can import them:

```python
BASE_URL = "http://localhost:8000"       # Where the FastAPI app is running

ADMIN_CREDS  = {"username": "amit_admin",   "password": "password123"}
COACH_CREDS  = {"username": "sunita_coach", "password": "password123"}
PLAYER_CREDS = {"username": "meera_player", "password": "password123"}

THREAD_COUNT  = 20      # How many concurrent threads for race tests
EQUIPMENT_QTY = 5       # Total equipment quantity for the race test
REQUEST_TIMEOUT = 15    # Per-request timeout so hangs show up clearly
```

**Why these values?** 
- `THREAD_COUNT=20` with `EQUIPMENT_QTY=5` means 20 threads fight over 5 items. This creates a 4:1 oversubscription — extreme enough to trigger race conditions if locks are broken, but not so extreme that the server just dies.
- The credentials must match seeded users that already exist in your database.
- `REQUEST_TIMEOUT` is important because it turns "the server got stuck" into a visible test failure instead of letting a request hang forever.

### helpers.py — Reusable Test Utilities

This file provides building blocks that all test files use:

**Login sessions:**
```python
def login_session(creds):
    cached_cookies = _AUTH_COOKIE_CACHE.get(cache_key)
    if cached_cookies is None:
        with _AUTH_COOKIE_LOCK:
            seed_session = requests.Session()
            r = seed_session.post(f"{BASE_URL}/auth/login", json=creds, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            cached_cookies = requests.utils.dict_from_cookiejar(seed_session.cookies)
    s = requests.Session()
    s.cookies = cookiejar_from_dict(cached_cookies)
    return s
```

A `requests.Session` automatically stores and sends cookies. We now do one real login per credential set, cache the cookie jar, and then create fresh sessions from that cached cookie state. That keeps the tests realistic while avoiding an unnecessary login storm.

**Why each thread still gets its own session:** In `test_race_conditions.py`, every thread still calls `coach_session()` or `admin_session()` to get its own independent session object. This simulates separate clients. The important difference is that those sessions no longer all have to hit `/auth/login` at once before the real test even starts.

**Test data factories:**
```python
def create_test_equipment(session, total_qty=5):
    payload = {
        "equipment_name": f"TestEquip_{_rand()}",   # Random name to avoid conflicts
        "total_quantity": total_qty,
        "equipment_condition": "New",
    }
    r = session.post(f"{BASE_URL}/api/equipment", json=payload)
    return r.json()["data"]["equipment_id"]
```

Every test creates its own fresh data with random names. This way:
1. Tests don't interfere with each other
2. Tests don't depend on specific data existing
3. You can run the suite multiple times without cleanup

**Direct DB access:**
```python
def get_db(database="olympia_track"):
    conn = mysql.connector.connect(host=..., database=database)
    return conn, conn.cursor(dictionary=True)
```

We connect directly to MySQL to verify results independently of the API. If we only used the API to check results, a bug in the API's read logic could mask a data corruption issue. Direct DB queries give us ground truth.

### verify.py — Post-Test Database Integrity Checker

This runs **6 SQL queries** against the database to check invariants (rules that must always be true):

| Check | What it verifies | SQL logic |
|-------|-----------------|-----------|
| Equipment invariant | Issued qty <= total qty for every item | `JOIN Equipment + EquipmentIssue`, look for `SUM(issued) > total` |
| No duplicate registrations | Each (tournament, team) pair appears at most once | `GROUP BY ... HAVING COUNT(*) > 1` |
| No duplicate member IDs | Every MemberID is unique (PRIMARY KEY integrity) | `GROUP BY MemberID HAVING COUNT(*) > 1` |
| Cross-DB consistency | Every `users.member_id` has a matching `Member` row | `LEFT JOIN` from users to Member, look for NULLs |
| No negative quantities | No equipment or issue has negative numbers | `WHERE TotalQuantity < 0` or `Quantity < 0` |
| No orphan members | Every Member row has a corresponding users row | `LEFT JOIN` from Member to users, look for NULLs |

**Why run these after every test?** Even if a test "passes" (the right number of API requests succeeded/failed), the database could still be in a bad state. These checks catch **silent corruption** that the API wouldn't report.

---

## 7. Race Condition Tests — Explained Step by Step

### RC-1: Equipment Issue Race (The Strongest Demo)

**Goal:** Prove that `FOR UPDATE` correctly prevents over-issuing equipment.

**Setup:**
1. Log in as admin and coach
2. Create a test player (the coach needs someone to issue equipment to)
3. Create a team under the coach and add the player to it (RBAC requires this)
4. Create equipment with `TotalQuantity = 5`

**The race:**
```python
with ThreadPoolExecutor(max_workers=20) as pool:
    futures = {pool.submit(issue_one, i): i for i in range(20)}
```

This launches **20 threads simultaneously**. Each thread:
1. Creates its own login session (to simulate a real separate user)
2. Sends `POST /api/equipment/issue` with `quantity=1`
3. Records whether it got HTTP 200 (success) or an error

**What happens inside the server:**
- Thread 1 arrives, executes `SELECT ... FOR UPDATE` — this **locks** the equipment row
- Threads 2-20 arrive, try to execute the same SELECT, but the row is **locked** — they **wait**
- Thread 1 sees `available = 5`, issues 1, commits. Lock is released. `available = 4` now.
- Thread 2 (which was waiting) now runs its SELECT, sees `available = 4`, issues 1. Lock released.
- ...continues until Thread 5 issues the last one. `available = 0`.
- Threads 6-20 each see `available = 0`, get "Only 0 available" error.

**Expected result:** Exactly 5 succeed, exactly 15 fail.

**DB verification:**
```sql
SELECT COALESCE(SUM(Quantity), 0) AS issued
FROM EquipmentIssue
WHERE EquipmentID = ? AND ReturnDate IS NULL
```
This must return exactly 5. If it returns 6+, the lock failed and we over-issued.

**Why this is the strongest demo:** It's visual and easy to explain. "5 balls, 20 people, only 5 got one." The `FOR UPDATE` lock is the mechanism that makes it work, and you can point to the exact SQL line in the code.

### RC-2: Tournament Registration Race

**Goal:** Prove that the UNIQUE constraint prevents duplicate registrations even without explicit locking.

**Setup:**
1. Create a tournament and a team
2. Launch 10 threads all trying to register the **same team** for the **same tournament**

**What happens:**
- All 10 threads hit the "check if already registered" SELECT at roughly the same time
- All 10 see "not registered yet" (because none have inserted yet)
- All 10 try to INSERT
- The first INSERT succeeds
- The remaining 9 fail because of the `UNIQUE(TournamentID, TeamID)` constraint in the database

**This demonstrates TOCTOU (Time-Of-Check-to-Time-Of-Use):** The check ("is it registered?") and the use ("insert registration") are not atomic. But the UNIQUE constraint acts as a safety net.

**Expected result:** Exactly 1 succeeds, exactly 9 fail. DB shows exactly 1 registration row.

### RC-3: Concurrent ID Generation

**Goal:** Verify that concurrent member creation produces unique IDs without timeouts or duplicate rows.

**Setup:** Launch 20 threads all creating new members simultaneously.

**What happens now:**
- All 20 requests race to create members at the same time
- `insert_with_generated_id()` takes a named MySQL lock for the Member ID generator
- The next ID is read on a short dedicated autocommit connection
- One request inserts, releases the lock, and the next request sees the updated `MAX(MemberID)`
- This serializes only the ID allocation step, which is the tiny critical section we actually care about

**Expected result:**
- All 20 requests are accounted for
- All 20 succeed in the normal race test
- Zero duplicate MemberIDs in the database

**Why we verify with SQL:**
```sql
SELECT MemberID, COUNT(*) FROM Member GROUP BY MemberID HAVING COUNT(*) > 1;
```
Must return 0 rows. If it returns anything, a duplicate primary key snuck through.

---

## 8. ACID Property Tests — Explained Step by Step

### Atomicity Test: Cross-DB Member Creation

**Goal:** Prove that creating a member is all-or-nothing across both databases.

**The test:**
1. Create a member normally (succeeds — establishes a username)
2. Try to create a SECOND member with the **same username** (the users INSERT will fail because `username` is UNIQUE)
3. Check: does a Member row exist for the second attempt?

**Before our bug fix:** The Member row WOULD exist (orphaned) because `return` instead of `raise` prevented rollback. This is the atomicity violation.

**After our bug fix:** The Member row does NOT exist because `raise HTTPException` triggers the rollback in `get_cross_db()`. Both the Member row and the users row are rolled back together.

**Why we test with a unique email:** We give the second payload a unique random email. Then we query `SELECT MemberID FROM Member WHERE Email = ?`. If a row comes back, we know the Member INSERT happened. Then we check if a matching users row exists. If the Member exists but the user doesn't — **atomicity violation!**

### Consistency Test: Invariant Checks

**Goal:** After running all the race condition tests, verify that no database rules were violated.

This runs the same checks as `verify.py`:
- Equipment issued qty never exceeds total qty
- No duplicate tournament registrations
- No negative quantities anywhere

**Why run it here as well as in verify.py?** Context. When this test runs as part of the ACID suite, it specifically proves that the **C** in ACID holds. When verify.py runs standalone, it's a general health check.

### Isolation Test 1: No Dirty Reads

**Goal:** Prove that one transaction can't see another's uncommitted changes.

This is the most complex test. Here's what happens step by step:

```
Timeline:
                    Thread A                    |          Thread B
-------------------------------------------------|----------------------------------
1. BEGIN TRANSACTION                             |
2. SELECT ... FOR UPDATE (locks equipment row)   |
3. INSERT issue (qty=3), but DON'T COMMIT yet    |
4. Signal to Thread B: "I'm ready"               |
5.                                               | Read equipment availability via API
6. Wait for commit signal...                     | Record the value seen
7. COMMIT                                        |
8.                                               | Read again
```

**What we check:**
- At step 5, Thread B should see the **original** availability (e.g., 10), NOT the reduced one (7). Thread A's insert hasn't been committed yet, so it should be invisible.
- At step 8 (after commit), Thread B should see the **new** availability (7).

**How we coordinate the threads:**
- `threading.Barrier(2)` — Both threads wait at the barrier until both arrive. This synchronizes them so B reads at the right moment.
- `threading.Event()` — Thread A waits for a signal before committing. This gives Thread B time to read.

**Why Thread A uses direct DB instead of the API:** The API auto-commits after each request (that's how `_get_cursor` works in `database.py`). We need a transaction that stays open, so we use a direct `mysql.connector` connection with `autocommit=False`.

**Why this matters:** MySQL's default isolation level (REPEATABLE READ) should prevent dirty reads. This test proves it works in our setup.

### Isolation Test 2: No Intermediate States

**Goal:** While equipment is being issued by many threads, every observed availability value must be a valid state.

**Setup:** Equipment with `TotalQuantity = 10`. Launch 8 issue threads (each issuing qty=1) and interleave 13 reader threads.

**What "valid state" means:**
- Availability must be an integer between 0 and 10
- It must be one of: 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, or 0
- It must NEVER be, say, 6.5, or -1, or 11

**Why could an intermediate state appear?** If the database didn't properly isolate transactions, a reader might catch a row mid-update — seeing a partially written value. This is theoretically impossible with InnoDB (MySQL's engine), but the test proves it empirically.

### Durability Test

**Goal:** Prove that committed data is actually stored permanently.

**The test:**
1. Create a member via API
2. Query the database directly — the member should be there
3. Query via API — the member should be there

**Why this is simple:** MySQL (InnoDB) guarantees durability through the **Write-Ahead Log (WAL)**. Every committed transaction is written to disk before the commit returns. Even if the server crashes immediately after, the data survives. Our test verifies this fundamental guarantee works.

**For your video demo:** You could enhance this by restarting MySQL between steps 1 and 2 to show data survives a restart. The code supports this but doesn't do it automatically since restarting MySQL requires sudo permissions.

---

## 9. Failure Simulation Tests — Explained Step by Step

### FS-1: Connection Kill During Operations

**Goal:** If MySQL connections are killed mid-operation, no partial records should be left behind.

**How it works:**
1. Start a **killer thread** that runs continuously in the background
2. The killer does `SHOW PROCESSLIST` (lists all MySQL connections) every 100ms
3. For any connection that's actively running a query (not sleeping), it runs `KILL <process_id>`
4. Meanwhile, 15 worker threads are creating members via the API

**What we're testing:** When a connection is killed mid-transaction, does MySQL properly roll back the incomplete work? Or do we get orphaned Member rows (Member created but users row lost because the connection died)?

**Expected result:**
- Many requests will fail (connection was killed)
- But NO partial records — every Member row has a matching users row
- This proves MySQL's transaction rollback works correctly on connection loss

**Why this matters in the real world:** Network issues, load balancer timeouts, and server restarts all kill connections unexpectedly. The app must handle this gracefully.

### FS-2: Pool Exhaustion

**Goal:** When more requests come in than the connection pool can handle, the system should degrade gracefully (errors, not corruption).

**Setup:**
- The current app pool is larger than the original version, but we still send **35 concurrent requests** to create deliberate connection pressure
- The goal is not "prove exactly the 6th request fails"; the goal is "prove the system degrades gracefully under resource pressure and then recovers"

**What happens:**
- A burst of concurrent work competes for pooled DB connections, row locks, CPU, and request slots
- Some requests may proceed, others may wait, and others may fail depending on timing
- The important property is that the system recovers afterward and does not corrupt data

**What we verify:**
1. Some requests succeed, many fail — that's expected and OK
2. After the burst subsides (all threads finish), the system **recovers** — new requests work normally
3. No data corruption — the equipment invariant (issued <= total) still holds

**Why 35 threads?** It's a strong enough burst to stress the current app configuration without turning the test into a pointless denial-of-service script.

### FS-3: Server Crash Simulation

**Goal:** Verify that database invariants hold even if the API server crashes.

**What we check:**
- Equipment quantity invariants are satisfied (issued <= total for all items)
- All committed data is still in the database

**Why we don't actually kill the server:** Automatically killing and restarting uvicorn is environment-dependent (different on Linux/Mac/Docker). Instead, we verify what matters: the **data** is safe because MySQL's durability guarantees it. The API server is stateless — restarting it just means reconnecting to MySQL.

**For your video demo:** You could manually kill the uvicorn process (`kill -9 <pid>`), restart it, and show that all data is intact. This is dramatic and makes a great demo.

---

## 10. Locust Stress Tests — Explained Step by Step

### What Locust Does

Locust simulates many virtual users hitting your API simultaneously. Each "user" is a Python class that:
1. Logs in when it starts
2. Randomly picks tasks to execute (weighted by frequency)
3. Waits 1-3 seconds between tasks (simulating think time)

### Our Three User Types

We modeled three user types matching our RBAC roles, with realistic **weight ratios**:

| User | Weight | Meaning | Why this weight |
|------|--------|---------|----------------|
| AdminUser | 1 | 1 admin per 10 users | Admins are rare — there's usually just one |
| CoachUser | 3 | 3 coaches per 10 users | Several coaches manage different teams |
| PlayerUser | 6 | 6 players per 10 users | Most users are players viewing their data |

With 100 total users, Locust would create ~10 admins, 30 coaches, and 60 players.

### Task Weights Explained

Each user type has tasks with different weights (relative frequencies):

**AdminUser tasks:**
```python
@task(5)    # 5/13 chance (~38%) — most common admin action
def list_members(self): ...

@task(3)    # 3/13 chance (~23%)
def list_equipment(self): ...

@task(1)    # 1/13 chance (~8%) — less common, creates data
def create_equipment(self): ...
```

**Why these weights?** They simulate realistic usage patterns:
- Read operations (listing) happen much more often than writes (creating)
- Players mostly view their own profile and browse events
- Coaches check their teams and issue equipment
- Admins do a mix of management tasks

### What Locust Measures

When you run Locust, it gives you:
- **Requests per second (RPS)** — how many requests the server handles
- **Response times** — p50 (median), p95 (95th percentile), p99 (99th percentile)
- **Error rate** — percentage of failed requests
- **Real-time charts** — watch performance as load increases

### Recommended Load Levels

| Level | Users | Duration | What it tests |
|-------|-------|----------|---------------|
| Light | 10 | 2 min | Baseline performance |
| Medium | 50 | 5 min | Moderate load |
| Heavy | 200 | 5 min | High load, near breaking point |
| Spike | 10 to 500 in 30s | 2 min | Sudden traffic spike (e.g., event goes viral) |

### Running Locust

**With web UI (recommended for demo):**
```bash
locust -f locustfile.py --host=http://localhost:8000
# Then open http://localhost:8089 in your browser
```

**Headless (for automated runs):**
```bash
locust -f locustfile.py --host=http://localhost:8000 --headless -u 50 -r 10 -t 2m
#   -u 50    = 50 total users
#   -r 10    = spawn 10 users/second
#   -t 2m    = run for 2 minutes
```

---

## 11. The Bug Fixes We Made

This turned out to be a multi-layer failure, not a one-line bug. We fixed several things that were interacting badly under concurrency.

### Fix 1: Proper Rollback in Cross-DB Member Creation

**File:** `app/routers/members.py`

**Before (buggy):**
```python
except Exception as e:
    write_audit_log(...)
    return {"success": False, "message": humanize_db_error(e), "data": body}
```

**After (fixed):**
```python
except Exception as e:
    write_audit_log(...)
    raise HTTPException(status_code=400, detail=humanize_db_error(e)) from e
```

This is what restored atomicity across `olympia_track.Member` and `olympia_auth.users`.

In the same member-creation path we also added `normalize_member_gender(...)`, so payloads like `Male`, `Female`, and `Other` are normalized to the database-safe `M`, `F`, and `O` values before insert.

```
                    BEFORE (buggy)                    |              AFTER (fixed)
------------------------------------------------------|---------------------------------------
1. Insert Member row -> SUCCESS                       | 1. Insert Member row -> SUCCESS
2. Insert users row -> FAILS (dup username)           | 2. Insert users row -> FAILS
3. `return {"success": False}` (no exception)         | 3. `raise HTTPException` (exception!)
4. get_cross_db sees no exception                     | 4. get_cross_db sees the exception
5. get_cross_db calls conn.COMMIT()                   | 5. get_cross_db calls conn.ROLLBACK()
6. Member row is SAVED (orphaned!)                    | 6. Member row is REMOVED (correct!)
```

### Fix 2: Add `API_CONTEXT_SECRET` So Normal API Writes Don't Trigger Tamper Logging

**Files:** `app/database.py`, `.env`, `.env.example`

The hidden performance killer was the missing API context secret. Without it, the database's tamper-detection triggers treated ordinary API writes as suspicious direct SQL writes and generated extra audit records inside MySQL.

That meant one application write could create trigger-generated writes behind the scenes, which is why the system looked fine at low load but fell apart during concurrency tests.

We fixed this by:
- adding `API_CONTEXT_SECRET` to the env files
- setting `@api_context` on DB connections
- failing fast at startup if the secret is missing

### Fix 3: Read New IDs Using a Fresh Autocommit View

**File:** `app/services/id_generation.py`

We kept the named-lock approach for ID generation, but changed the "what is the next ID?" read to happen on a short dedicated autocommit connection.

This matters because retries now see the latest committed `MAX(ID)` value instead of getting stuck on a stale snapshot from an older transaction.

### Fix 3.5: Translate Registration/Participation Duplicate-Key Races Into Clean 409s

**File:** `app/routers/registration.py`

The UNIQUE constraints were already the real safety net, but we now explicitly catch duplicate-key exceptions from the insert path and convert them into clean HTTP `409 Conflict` responses.

That means the race is still resolved by the database, but the API now reports it in a controlled, user-friendly way instead of surfacing a raw low-level DB error.

### Fix 4: Decouple Audit Writes From Business Transactions

**File:** `app/services/audit.py`

Audit writes now use their own short-lived autocommit auth connection.

That prevents a long-running request transaction from holding the audit chain hostage, and it also prevents audit contention from poisoning unrelated endpoints.

### Fix 5: Make Test Logins Thread-Safe and Reusable

**File:** `loadtest/helpers.py`

The test helper now caches login cookies behind a lock and creates new `requests.Session()` objects from that cached cookie jar.

This makes the load tests cleaner because they stress the endpoint under test, not `/auth/login`.

### How We Test All of This

- The atomicity test confirms there are no orphan Member rows
- The race-condition tests confirm equipment issuing, registration, and member creation all behave correctly under concurrency
- The final verification pass confirms the database is still consistent after the whole suite
- After these fixes, the full `run_all.py` suite completed with all 11 tests passing

---

## 12. The Verification System

### verify.py — The Safety Net

After every test phase, `verify.py` runs 6 SQL checks against the database. Think of it as a "doctor's checkup" for the database.

Each check follows the same pattern:
1. Run a SQL query that looks for violations
2. If the query returns 0 rows, the check PASSES (no violations found)
3. If it returns rows, the check FAILS (violations exist)

**Example — Equipment Invariant Check:**
```sql
SELECT e.EquipmentID, e.TotalQuantity,
       COALESCE(SUM(ei.Quantity), 0) AS issued
FROM Equipment e
LEFT JOIN EquipmentIssue ei
       ON e.EquipmentID = ei.EquipmentID AND ei.ReturnDate IS NULL
GROUP BY e.EquipmentID, e.TotalQuantity
HAVING issued > e.TotalQuantity    -- Only return rows where MORE was issued than exists
```

If this returns any rows, it means we issued more equipment than we have — the FOR UPDATE lock failed.

### run_all.py — The Orchestrator

This file runs everything in order and generates a report:

```
Phase 1: Race Condition Tests (RC-1, RC-2, RC-3)
Phase 2: ACID Property Tests (Atomicity, Consistency, Isolation x2, Durability)
Phase 3: Failure Simulation Tests (FS-1, FS-2, FS-3)
Phase 4: Post-Test Database Verification (6 checks)
```

At the end, it generates `results/report.md` — a Markdown table summarizing all results with PASS/FAIL for each test.

---

## 13. How to Run Everything

### Prerequisites

1. Make sure MySQL is running and the databases `olympia_auth` and `olympia_track` exist with data
2. Make sure the FastAPI app is running (`uvicorn app.main:app`)
3. Make sure the test users (admin, coach1, player1) exist in the database
4. Make sure `API_CONTEXT_SECRET` is present in `Module_B/.env`, otherwise normal API writes may be mistaken for direct DB tampering by the MySQL triggers

### Install Dependencies

```bash
cd Module_B
pip install -r requirements.txt
```

This adds `locust` and `tabulate` to the existing requirements.

### Run the Full Suite

```bash
cd Module_B/loadtest
python run_all.py
```

This runs all tests and generates `results/report.md`.

### Run Individual Test Files

```bash
python test_race_conditions.py    # Just race condition tests
python test_acid.py               # Just ACID tests
python test_failure.py            # Just failure tests
python verify.py                  # Just database checks
```

### Run Locust Stress Test

```bash
locust -f locustfile.py --host=http://localhost:8000
# Open http://localhost:8089 in your browser
# Set number of users and spawn rate, click Start
```

---

## 14. What to Show in Your Video Demo

### Recommended Demo Flow (5-10 minutes)

1. **Show the app is running** — Open the browser, show the UI, show a few API calls working

2. **Run the race condition tests** — `python test_race_conditions.py`
   - Highlight RC-1: "20 threads, 5 items, exactly 5 succeed"
   - Show the terminal output with the counts
   - Explain FOR UPDATE is why it works

3. **Run the ACID tests** — `python test_acid.py`
   - Show the atomicity test: "Duplicate username causes rollback, no orphan rows"
   - Mention that the fix is now bigger than one line: rollback, API context tagging, and safer ID generation all work together

4. **Run Locust** — `locust -f locustfile.py --host=http://localhost:8000`
   - Start with 10 users, ramp to 50
   - Show the live charts (RPS, response times)
   - Point out that error rate stays at 0% under moderate load

5. **Run verification** — `python verify.py`
   - Show all 6 checks passing: "Even after all that stress, the database is perfectly consistent"

6. **Show the generated report** — Open `results/report.md`

### Key Talking Points

- "We found and fixed an atomicity bug in member creation"
- "We found a hidden configuration bug too: without `API_CONTEXT_SECRET`, normal API writes were being treated like direct DB access by the tamper-detection triggers"
- "We changed ID generation so retries see fresh committed IDs instead of stale snapshot values"
- "FOR UPDATE correctly prevents equipment over-issuing under 20 concurrent threads"
- "The UNIQUE constraint acts as a safety net for registration races"
- "MySQL's isolation prevents dirty reads — uncommitted data is invisible"
- "Even when we kill database connections mid-operation, no data corruption occurs"
- "The system handles 50 concurrent users with sub-second response times"

---

## Design Decisions Summary

| Decision | Why |
|----------|-----|
| Test via HTTP API, not direct DB | Tests the full stack as a real user would experience it |
| Verify via direct DB queries | Catches corruption that the API might not report |
| Each thread gets its own session | Simulates independent users, not one user with multiple tabs |
| Random test data names | Tests are idempotent — run them 100 times without cleanup |
| 20 threads for races | High enough to trigger races, low enough to not crash the server |
| 35-thread burst for exhaustion testing | Large enough to create contention and verify graceful recovery |
| Barrier + Event for isolation test | Precise thread coordination to catch dirty reads |
| `raise` instead of `return` in member creation | Lets `get_cross_db()` roll back both databases on failure |
| Normalize member gender before insert | Prevents invalid enum values from breaking member creation |
| Require `API_CONTEXT_SECRET` | Prevents tamper triggers from auditing normal API writes |
| Named lock + fresh autocommit ID read | Prevents stale-snapshot `MAX+1` collisions |
| Catch duplicate-key races in registration | Returns clean `409 Conflict` responses instead of raw DB failures |
| Separate audit connection | Keeps audit writes from blocking on business transactions |
| Thread-safe cached login cookies | Keeps load tests focused on the real target endpoint |
| Locust weights 1:3:6 | Realistic ratio of admin:coach:player traffic |
| Separate verification pass | Defense in depth — even if tests pass, verify DB state independently |
