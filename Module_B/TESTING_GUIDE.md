# Olympia Track — Run & Test Guide
## CS 432 Databases | Module B

---

## Table of Contents
1. [Setup](#1-setup)
2. [Starting the Server](#2-starting-the-server)
3. [Demo Accounts](#3-demo-accounts)
4. [UI Walkthrough](#4-ui-walkthrough)
5. [API Testing (curl)](#5-api-testing-curl)
   - [Auth](#51-auth)
   - [Members](#52-members)
   - [Teams](#53-teams)
   - [Tournaments & Events](#54-tournaments--events)
   - [Equipment](#55-equipment)
   - [Performance Logs](#56-performance-logs)
   - [Medical Records](#57-medical-records)
   - [Admin — Audit Log](#58-admin--audit-log)
6. [RBAC Test Matrix](#6-rbac-test-matrix)
7. [Audit Chain Tamper Demo](#7-audit-chain-tamper-demo)
8. [Interactive API Docs](#8-interactive-api-docs)

---

## 1. Setup

### Prerequisites
- Python 3.10+
- MySQL 8.0 (running)
- `pip` available

### One-time database setup

```bash
cd Module_B

# Install Python deps
pip install -r requirements.txt

# Create databases and seed data (run as MySQL root via sudo)
printf "<pass>\n" | sudo -S bash -c '
  mysql -u root < sql/01_core_tables.sql &&
  mysql -u root < sql/02_project_tables.sql &&
  mysql -u root < sql/03_seed_users.sql
'

# Create the app DB user (if not already done)
printf "<pass>\n" | sudo -S mysql -u root -e "
  CREATE USER IF NOT EXISTS 'olympia_app'@'localhost' IDENTIFIED BY 'olympia_pass';
  GRANT ALL PRIVILEGES ON olympia_auth.*  TO 'olympia_app'@'localhost';
  GRANT ALL PRIVILEGES ON olympia_track.* TO 'olympia_app'@'localhost';
  FLUSH PRIVILEGES;
"
```

> **What gets created:**
> - `olympia_auth` database — `users` (3 seed accounts), `sessions`, `audit_log`
> - `olympia_track` database — 13 tables with 20 members, 15 teams, 15 events, and all sample data
> - MySQL user `olympia_app` / `olympia_pass` — used by the app (never needs `sudo`)

---

## 2. Starting the Server

```bash
cd Module_B
uvicorn app.main:app --reload --port 8000
```

Open your browser at **http://localhost:8000** — it redirects to the login page.

To run in background:
```bash
uvicorn app.main:app --port 8000 &
```

Health check:
```bash
curl http://localhost:8000/health
# {"olympia_auth":"ok","olympia_track":"ok"}
```

---

## 3. Demo Accounts

| Username | Password | Role | MemberID | Who |
|---|---|---|---|---|
| `vikram_admin` | `admin123` | Admin | 18 | Vikram Reddy |
| `raj_coach` | `coach123` | Coach | 13 | Raj Kumar (coaches teams 1,2,3,13) |
| `aarav_player` | `player123` | Player | 1 | Aarav Sharma |

---

## 4. UI Walkthrough

All UI pages are at `/ui/*`. Start from **http://localhost:8000**.

### Step 1 — Login as Admin
1. Go to http://localhost:8000/ui/login
2. Enter `vikram_admin` / `admin123` → click **Sign in**
3. You land on the **Dashboard** showing:
   - 20 members, 15 teams, 8 sports
   - Upcoming/ongoing events count
   - 15 equipment items, 5 currently unreturned
   - Table of upcoming events and active tournaments

### Step 2 — Browse Members
- Click **Members** in sidebar → see all 20 members
- Use the **search box** — type "Aarav" to filter live
- Click **View** on any member → see their **portfolio page**:
  - Profile card (name, email, role, age, contact, join date)
  - Teams they're on (with position and captain badge)
  - Performance history table
  - Medical records (Admin and own-member only)
- Click **Add Member** (top right) → fill form → creates member + auth account
- Click **Edit** on a member → update name/email/age/contact
- Click **Delete** → confirm dialog → member removed

### Step 3 — Browse Teams
- Click **Teams** → see all 15 teams with sport and coach
- Click any team → see team detail with full roster (names, positions, captain flag)
- Links from roster go back to member portfolios

### Step 4 — Browse Events
- Click **Events** → all 15 events listed
- Use the **status dropdown** to filter: Scheduled / Ongoing / Completed
- Click any event → see event detail with participating teams and results/scores

### Step 5 — Equipment
- Click **Equipment** → two tables:
  - Full inventory (15 items) with condition badges
  - Currently active issues (items not yet returned)

### Step 6 — Audit Log (Admin only)
- Click **Audit Log** in sidebar
- See the last 100 log entries with timestamps, user, action, table, status, hash prefix
- Click **Verify Chain Integrity** → sends request to `/admin/verify-audit`
- Should show: *"Chain intact — N entries verified"*

### Step 7 — Test RBAC in UI
Log out (click username dropdown → Logout) and log in as:

**Coach (`raj_coach` / `coach123`):**
- Sidebar shows no Audit Log link
- Members page shows all members (Coaches can view all)
- Try going to `/ui/admin/audit` directly → redirected to dashboard

**Player (`aarav_player` / `player123`):**
- Members page shows **only own profile** (1 row)
- Try going to `/ui/members/2` directly → redirected to `/ui/members/1`
- Portfolio shows own performance logs and medical records
- Audit Log link hidden in sidebar

---

## 5. API Testing (curl)

### Cookie setup — login first

```bash
# Admin session
curl -s -c /tmp/admin.txt -X POST http://localhost:8000/ui/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=vikram_admin&password=admin123"

# Coach session
curl -s -c /tmp/coach.txt -X POST http://localhost:8000/ui/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=raj_coach&password=coach123"

# Player session
curl -s -c /tmp/player.txt -X POST http://localhost:8000/ui/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=aarav_player&password=player123"
```

Or use the JSON API:
```bash
curl -s -c /tmp/admin.txt -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"vikram_admin","password":"admin123"}'
```

---

### 5.1 Auth

#### Login
```bash
curl -s -c /tmp/admin.txt -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"vikram_admin","password":"admin123"}'
# Expected: {"success":true,"data":{"role":"Admin","member_id":18,...}}
```

#### Wrong password
```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"vikram_admin","password":"wrong"}'
# Expected: 401 {"detail":"Invalid credentials"}
```

#### Check auth status
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/auth/isAuth
# Expected: {"success":true,"data":{"username":"vikram_admin","role":"Admin",...}}
```

#### Logout
```bash
curl -s -b /tmp/admin.txt -c /tmp/admin.txt http://localhost:8000/auth/logout
# Expected: {"success":true,"message":"Logged out"}

curl -s -b /tmp/admin.txt http://localhost:8000/auth/isAuth
# Expected: 401 {"detail":"Not authenticated"}  (cookie cleared, session revoked)
```

> Re-login for subsequent tests:
> ```bash
> curl -s -c /tmp/admin.txt -X POST http://localhost:8000/auth/login \
>   -H "Content-Type: application/json" \
>   -d '{"username":"vikram_admin","password":"admin123"}'
> ```

---

### 5.2 Members

#### List all members (Admin — sees all 20)
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/api/members | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('count:', len(d['data']))"
# Expected: count: 20
```

#### List members (Player — sees only self)
```bash
curl -s -b /tmp/player.txt http://localhost:8000/api/members | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('count:', len(d['data']), '| name:', d['data'][0]['Name'])"
# Expected: count: 1 | name: Aarav Sharma
```

#### Get my own profile
```bash
curl -s -b /tmp/player.txt http://localhost:8000/api/members/me | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['data']['Name'])"
# Expected: Aarav Sharma
```

#### Get member portfolio (Admin viewing member 1)
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/api/members/1 | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)['data']
print('Member:', d['member']['Name'])
print('Teams:', [t['TeamName'] for t in d['teams']])
print('Perf logs:', len(d['performance']))
print('Medical:', len(d['medical']))
"
# Expected: Member: Aarav Sharma, 2 teams, 5 perf logs, 2 medical records
```

#### Player accessing another member's portfolio (should 403)
```bash
curl -s -b /tmp/player.txt http://localhost:8000/api/members/2
# Expected: {"detail":"Access denied"}
```

#### Create a new member (Admin only)
```bash
curl -s -b /tmp/admin.txt -X POST http://localhost:8000/api/members \
  -H "Content-Type: application/json" \
  -d '{
    "member_id": 21,
    "name": "New Player",
    "age": 20,
    "email": "newplayer@iitgn.ac.in",
    "contact_number": "9000000001",
    "gender": "M",
    "role": "Player",
    "join_date": "2026-03-14",
    "username": "new_player",
    "password": "newpass123"
  }'
# Expected: {"success":true,"message":"Member created","data":{"member_id":21}}
```

#### Create member (Coach — should 403)
```bash
curl -s -b /tmp/coach.txt -X POST http://localhost:8000/api/members \
  -H "Content-Type: application/json" \
  -d '{"member_id":99,"name":"X","age":20,"email":"x@x.com","contact_number":"1","gender":"M","role":"Player","join_date":"2026-01-01","username":"x","password":"x"}'
# Expected: 403 {"detail":"Access denied. Required role(s): ['Admin']"}
```

#### Update a member (Admin or own profile)
```bash
curl -s -b /tmp/admin.txt -X PUT http://localhost:8000/api/members/21 \
  -H "Content-Type: application/json" \
  -d '{"name":"Updated Player","age":21}'
# Expected: {"success":true,"message":"Member updated"}
```

#### Delete a member (Admin only)
```bash
curl -s -b /tmp/admin.txt -X DELETE http://localhost:8000/api/members/21
# Expected: {"success":true,"message":"Member 21 deleted"}
```

---

### 5.3 Teams

#### List all teams
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/api/teams | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('count:', len(d['data']))"
# Expected: count: 15
```

#### Get team detail with roster
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/api/teams/9 | \
  python3 -c "
import sys,json
d = json.load(sys.stdin)['data']
print('Team:', d['team']['TeamName'])
print('Roster:', [r['Name'] for r in d['roster']])
"
# Expected: Team: IITGN FC Alpha, Roster: [Vikash Yadav, Rohan Das, Arjun Mehta, Harsh Pandey]
```

#### Create team (Admin)
```bash
curl -s -b /tmp/admin.txt -X POST http://localhost:8000/api/teams \
  -H "Content-Type: application/json" \
  -d '{"team_id":16,"team_name":"Test Team","sport_id":1,"formed_date":"2026-03-14","coach_id":13}'
# Expected: {"success":true,"message":"Team created","data":{"team_id":16}}
```

#### Coach updating own team (team 1 is coached by Raj Kumar, CoachID=13)
```bash
curl -s -b /tmp/coach.txt -X PUT http://localhost:8000/api/teams/1 \
  -H "Content-Type: application/json" \
  -d '{"team_name":"Thunder Sprinters Updated"}'
# Expected: {"success":true,"message":"Team updated"}
```

#### Coach updating another coach's team (should 403)
```bash
curl -s -b /tmp/coach.txt -X PUT http://localhost:8000/api/teams/6 \
  -H "Content-Type: application/json" \
  -d '{"team_name":"Hijacked Team"}'
# Expected: {"detail":"Coach can only update their own teams"}
```

#### Delete team (Admin, cleanup)
```bash
curl -s -b /tmp/admin.txt -X DELETE http://localhost:8000/api/teams/16
# Expected: {"success":true,"message":"Team 16 deleted"}
```

---

### 5.4 Tournaments & Events

#### List tournaments
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/api/tournaments | \
  python3 -c "import sys,json; [print(t['TournamentName'], '|', t['Status']) for t in json.load(sys.stdin)['data']]"
```

#### Create tournament (Admin only)
```bash
curl -s -b /tmp/admin.txt -X POST http://localhost:8000/api/tournaments \
  -H "Content-Type: application/json" \
  -d '{"tournament_id":5,"tournament_name":"Test Cup","start_date":"2026-06-01","end_date":"2026-06-10","status":"Upcoming"}'
# Expected: {"success":true,"message":"Tournament created"}
```

#### Create tournament (Player — should 403)
```bash
curl -s -b /tmp/player.txt -X POST http://localhost:8000/api/tournaments \
  -H "Content-Type: application/json" \
  -d '{"tournament_id":6,"tournament_name":"Hacker Cup","start_date":"2026-01-01","end_date":"2026-01-02","status":"Upcoming"}'
# Expected: 403
```

#### List all events
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/api/events | \
  python3 -c "import sys,json; print('count:', len(json.load(sys.stdin)['data']))"
# Expected: count: 15
```

#### Filter events by status
```bash
curl -s -b /tmp/admin.txt "http://localhost:8000/api/events?status=Scheduled" | \
  python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print('Scheduled:', len(d))"
# Expected: Scheduled: 6

curl -s -b /tmp/admin.txt "http://localhost:8000/api/events?status=Ongoing" | \
  python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print('Ongoing:', len(d))"
# Expected: Ongoing: 1
```

#### Filter events by tournament
```bash
curl -s -b /tmp/admin.txt "http://localhost:8000/api/events?tournament_id=2" | \
  python3 -c "import sys,json; print('Events in tournament 2:', len(json.load(sys.stdin)['data']))"
# Expected: 7
```

#### Get event detail with participation
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/api/events/1 | \
  python3 -c "
import sys,json
d = json.load(sys.stdin)['data']
print('Event:', d['event']['EventName'])
print('Participants:', len(d['participation']))
"
```

---

### 5.5 Equipment

#### List inventory
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/api/equipment | \
  python3 -c "import sys,json; print('items:', len(json.load(sys.stdin)['data']))"
# Expected: items: 15
```

#### List all issues (Admin sees all)
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/api/equipment/issues | \
  python3 -c "import sys,json; print('issues:', len(json.load(sys.stdin)['data']))"
# Expected: issues: 18
```

#### Player sees only own issues
```bash
curl -s -b /tmp/player.txt http://localhost:8000/api/equipment/issues | \
  python3 -c "
import sys,json
d = json.load(sys.stdin)['data']
print('issues for player:', len(d))
if d: print('member:', d[0]['MemberName'])
"
```

#### Issue equipment (Admin/Coach only)
```bash
curl -s -b /tmp/coach.txt -X POST http://localhost:8000/api/equipment/issue \
  -H "Content-Type: application/json" \
  -d '{"issue_id":19,"equipment_id":2,"member_id":5,"issue_date":"2026-03-14","quantity":1}'
# Expected: {"success":true,"message":"Equipment issued"}
```

#### Player trying to issue (should 403)
```bash
curl -s -b /tmp/player.txt -X POST http://localhost:8000/api/equipment/issue \
  -H "Content-Type: application/json" \
  -d '{"issue_id":20,"equipment_id":2,"member_id":1,"issue_date":"2026-03-14","quantity":1}'
# Expected: 403
```

#### Mark equipment returned
```bash
curl -s -b /tmp/admin.txt -X PUT \
  "http://localhost:8000/api/equipment/issue/19/return?return_date=2026-03-15"
# Expected: {"success":true,"message":"Equipment returned"}
```

---

### 5.6 Performance Logs

#### Admin sees all 20 logs
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/api/performance-logs | \
  python3 -c "import sys,json; print('logs (admin):', len(json.load(sys.stdin)['data']))"
# Expected: 20
```

#### Coach sees only their team's players' logs
```bash
curl -s -b /tmp/coach.txt http://localhost:8000/api/performance-logs | \
  python3 -c "
import sys,json
d = json.load(sys.stdin)['data']
print('logs (coach):', len(d))
members = set(r['MemberName'] for r in d)
print('members:', members)
"
# Expected: 9 logs (players on Raj Kumar's teams)
```

#### Player sees only own logs
```bash
curl -s -b /tmp/player.txt http://localhost:8000/api/performance-logs | \
  python3 -c "
import sys,json
d = json.load(sys.stdin)['data']
print('logs (player):', len(d))
print('all for:', set(r['MemberName'] for r in d))
"
# Expected: 5 logs, all for Aarav Sharma
```

#### Create performance log (Coach)
```bash
curl -s -b /tmp/coach.txt -X POST http://localhost:8000/api/performance-logs \
  -H "Content-Type: application/json" \
  -d '{"log_id":21,"member_id":1,"sport_id":1,"metric_name":"100m Time (s)","metric_value":10.70,"record_date":"2026-03-14"}'
# Expected: {"success":true,"message":"Performance log created"}
```

#### Player trying to create (should 403)
```bash
curl -s -b /tmp/player.txt -X POST http://localhost:8000/api/performance-logs \
  -H "Content-Type: application/json" \
  -d '{"log_id":22,"member_id":1,"sport_id":1,"metric_name":"100m Time (s)","metric_value":10.60,"record_date":"2026-03-14"}'
# Expected: 403
```

---

### 5.7 Medical Records

#### Admin accesses any member's records
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/api/medical-records/1 | \
  python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print('records:', len(d), '| conditions:', [r['MedicalCondition'] for r in d])"
```

#### Player accesses own records
```bash
curl -s -b /tmp/player.txt http://localhost:8000/api/medical-records/1 | \
  python3 -c "import sys,json; print('own records:', len(json.load(sys.stdin)['data']))"
# Expected: 2 records
```

#### Player accessing another member's records (should 403)
```bash
curl -s -b /tmp/player.txt http://localhost:8000/api/medical-records/2
# Expected: {"detail":"Access denied"}
```

#### Coach accessing medical records (should 403 — medical is Admin/self only)
```bash
curl -s -b /tmp/coach.txt http://localhost:8000/api/medical-records/1
# Expected: {"detail":"Access denied"}
```

#### Create medical record (Admin only)
```bash
curl -s -b /tmp/admin.txt -X POST http://localhost:8000/api/medical-records \
  -H "Content-Type: application/json" \
  -d '{"record_id":16,"member_id":2,"medical_condition":"Knee Sprain","diagnosis_date":"2026-03-14","status":"Active"}'
# Expected: {"success":true,"message":"Medical record created"}
```

---

### 5.8 Admin — Audit Log

#### View last 100 audit entries
```bash
curl -s -b /tmp/admin.txt "http://localhost:8000/admin/audit-log?limit=20" | \
  python3 -c "
import sys,json
rows = json.load(sys.stdin)['data']
print(f'{len(rows)} entries (newest first):')
for r in rows[:5]:
    print(f\"  [{r['log_id']}] {r['username']} | {r['action']} | {r['table_name']} | {r['status']}\")
"
```

#### Player/Coach trying to view audit log (should 403)
```bash
curl -s -b /tmp/player.txt http://localhost:8000/admin/audit-log
# Expected: 403

curl -s -b /tmp/coach.txt http://localhost:8000/admin/audit-log
# Expected: 403
```

#### Verify chain integrity (intact)
```bash
curl -s -b /tmp/admin.txt http://localhost:8000/admin/verify-audit
# Expected: {"success":true,"data":{"intact":true,"total_entries":N}}
```

---

## 6. RBAC Test Matrix

Run this complete matrix to confirm all access controls:

```bash
# Re-login all three sessions
curl -sc /tmp/admin.txt  -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d '{"username":"vikram_admin","password":"admin123"}' > /dev/null
curl -sc /tmp/coach.txt  -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d '{"username":"raj_coach","password":"coach123"}' > /dev/null
curl -sc /tmp/player.txt -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d '{"username":"aarav_player","password":"player123"}' > /dev/null

echo "--- Members ---"
echo -n "Admin  GET /api/members:         " && curl -so /dev/null -w "%{http_code}" -b /tmp/admin.txt  http://localhost:8000/api/members
echo -n "Coach  GET /api/members:         " && curl -so /dev/null -w "%{http_code}" -b /tmp/coach.txt  http://localhost:8000/api/members
echo -n "Player GET /api/members:         " && curl -so /dev/null -w "%{http_code}" -b /tmp/player.txt http://localhost:8000/api/members
echo -n "Player GET /api/members/2:       " && curl -so /dev/null -w "%{http_code}" -b /tmp/player.txt http://localhost:8000/api/members/2
echo -n "Coach  DELETE /api/members/1:    " && curl -so /dev/null -w "%{http_code}" -b /tmp/coach.txt  -X DELETE http://localhost:8000/api/members/1
echo -n "Player DELETE /api/members/1:    " && curl -so /dev/null -w "%{http_code}" -b /tmp/player.txt -X DELETE http://localhost:8000/api/members/1

echo ""
echo "--- Performance ---"
echo -n "Admin  GET /api/performance-logs: " && curl -so /dev/null -w "%{http_code}" -b /tmp/admin.txt  http://localhost:8000/api/performance-logs
echo -n "Player POST /api/performance-logs:" && curl -so /dev/null -w "%{http_code}" -b /tmp/player.txt -X POST http://localhost:8000/api/performance-logs -H "Content-Type: application/json" -d '{"log_id":99,"member_id":1,"sport_id":1,"metric_name":"x","metric_value":1,"record_date":"2026-01-01"}'

echo ""
echo "--- Medical ---"
echo -n "Admin  GET /api/medical-records/1: " && curl -so /dev/null -w "%{http_code}" -b /tmp/admin.txt  http://localhost:8000/api/medical-records/1
echo -n "Player GET /api/medical-records/1: " && curl -so /dev/null -w "%{http_code}" -b /tmp/player.txt http://localhost:8000/api/medical-records/1
echo -n "Player GET /api/medical-records/2: " && curl -so /dev/null -w "%{http_code}" -b /tmp/player.txt http://localhost:8000/api/medical-records/2
echo -n "Coach  GET /api/medical-records/1: " && curl -so /dev/null -w "%{http_code}" -b /tmp/coach.txt  http://localhost:8000/api/medical-records/1

echo ""
echo "--- Admin audit ---"
echo -n "Admin  GET /admin/audit-log:      " && curl -so /dev/null -w "%{http_code}" -b /tmp/admin.txt  http://localhost:8000/admin/audit-log
echo -n "Coach  GET /admin/audit-log:      " && curl -so /dev/null -w "%{http_code}" -b /tmp/coach.txt  http://localhost:8000/admin/audit-log
echo -n "Player GET /admin/audit-log:      " && curl -so /dev/null -w "%{http_code}" -b /tmp/player.txt http://localhost:8000/admin/audit-log
echo ""
```

**Expected output:**
```
--- Members ---
Admin  GET /api/members:         200
Coach  GET /api/members:         200
Player GET /api/members:         200  ← returns only own row
Player GET /api/members/2:       403
Coach  DELETE /api/members/1:    403
Player DELETE /api/members/1:    403

--- Performance ---
Admin  GET /api/performance-logs: 200
Player POST /api/performance-logs:403

--- Medical ---
Admin  GET /api/medical-records/1: 200
Player GET /api/medical-records/1: 200  ← own records
Player GET /api/medical-records/2: 403
Coach  GET /api/medical-records/1: 403

--- Admin audit ---
Admin  GET /admin/audit-log:      200
Coach  GET /admin/audit-log:      403
Player GET /admin/audit-log:      403
```

---

## 7. Audit Chain Tamper Demo

This demonstrates the hash chain tamper detection.

```bash
# Step 1 — verify chain is intact
curl -s -b /tmp/admin.txt http://localhost:8000/admin/verify-audit
# Expected: {"success":true,"data":{"intact":true,"total_entries":N}}

# Step 2 — directly tamper with a log row in MySQL (bypassing the API)
printf "<pass>\n" | sudo -S mysql -u root -e \
  "UPDATE olympia_auth.audit_log SET action='TAMPERED' WHERE log_id=1;"

# Step 3 — verify again — chain should be broken
curl -s -b /tmp/admin.txt http://localhost:8000/admin/verify-audit
# Expected: {"success":true,"data":{"intact":false,"tampered_at_log_id":1}}

# Step 4 — restore the row
printf "<pass>\n" | sudo -S mysql -u root -e \
  "UPDATE olympia_auth.audit_log SET action='LOGIN' WHERE log_id=1;"

# Step 5 — verify chain is intact again
curl -s -b /tmp/admin.txt http://localhost:8000/admin/verify-audit
# Expected: {"success":true,"data":{"intact":true,"total_entries":N}}
```

> **How it works:** Every audit entry stores `prev_hash` (hash of the previous entry) and `entry_hash` (SHA-256 of all its own fields + `prev_hash`). Changing any field in any entry breaks its hash, which breaks every subsequent entry's `prev_hash` check. The verify endpoint recomputes and compares every entry in chain order.

You can also see this visually in the UI:
1. Go to **http://localhost:8000/ui/admin/audit**
2. Click **Verify Chain Integrity** — shows green "Chain intact"
3. Run the tamper SQL above
4. Click the button again — shows red "Chain BROKEN at log_id=1"

---

## 8. Interactive API Docs

FastAPI auto-generates interactive docs. With the server running:

- **Swagger UI:** http://localhost:8000/docs
  - Click any endpoint → **Try it out** → fill params → **Execute**
  - Note: cookie auth won't work directly in Swagger; use curl with `-b /tmp/admin.txt` instead

- **ReDoc:** http://localhost:8000/redoc
  - Read-only reference for all endpoints, models, and responses

---

## Quick Reference — All Endpoints

| Method | URL | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/login` | public | Login, get JWT cookie |
| `GET` | `/auth/logout` | any | Logout, revoke session |
| `GET` | `/auth/isAuth` | any | Check session status |
| `GET` | `/api/members` | any | List members (RBAC filtered) |
| `GET` | `/api/members/me` | any | Own profile |
| `GET` | `/api/members/{id}` | any | Member portfolio (RBAC) |
| `POST` | `/api/members` | Admin | Create member + auth account |
| `PUT` | `/api/members/{id}` | Admin/self | Update member |
| `DELETE` | `/api/members/{id}` | Admin | Delete member |
| `GET` | `/api/teams` | any | List teams |
| `GET` | `/api/teams/{id}` | any | Team + roster |
| `POST` | `/api/teams` | Admin | Create team |
| `PUT` | `/api/teams/{id}` | Admin/Coach(own) | Update team |
| `DELETE` | `/api/teams/{id}` | Admin | Delete team |
| `GET` | `/api/tournaments` | any | List tournaments |
| `POST` | `/api/tournaments` | Admin | Create tournament |
| `GET` | `/api/events` | any | List events (filterable) |
| `GET` | `/api/events/{id}` | any | Event detail + participation |
| `POST` | `/api/events` | Admin | Create event |
| `GET` | `/api/equipment` | any | Equipment inventory |
| `GET` | `/api/equipment/issues` | any | Issue records (RBAC filtered) |
| `POST` | `/api/equipment/issue` | Admin/Coach | Issue equipment |
| `PUT` | `/api/equipment/issue/{id}/return` | Admin/Coach | Mark returned |
| `GET` | `/api/performance-logs` | any | Perf logs (RBAC filtered) |
| `POST` | `/api/performance-logs` | Admin/Coach | Add log entry |
| `GET` | `/api/medical-records/{id}` | Admin/self | Medical records |
| `POST` | `/api/medical-records` | Admin | Create medical record |
| `GET` | `/admin/audit-log` | Admin | View audit entries |
| `GET` | `/admin/verify-audit` | Admin | Verify hash chain |
| `GET` | `/health` | public | DB connectivity check |

---

*Olympia Track | CS 432 Databases | Module B*
