"""ACID Property Tests: Atomicity, Consistency, Isolation, Durability."""

import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from helpers import (
    admin_session, coach_session, get_db, close_db,
    create_test_equipment, create_test_member_payload,
    get_coach_member_id, create_test_team,
)
from config import BASE_URL


def _banner(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


# ── Atomicity: Cross-DB member creation ────────────────────────────────────

def test_atomicity_cross_db():
    """Create member with duplicate username — Member row must NOT exist if users INSERT fails.

    Before the bug fix: Member row will be orphaned (demonstrating the violation).
    After the bug fix: Member row will be rolled back.
    """
    _banner("ACID - Atomicity: Cross-DB Member Creation")

    admin = admin_session()

    # Step 1: Create a member normally
    payload1 = create_test_member_payload("Player")
    r1 = admin.post(f"{BASE_URL}/api/members", json=payload1)
    r1.raise_for_status()
    original_username = payload1["username"]
    print(f"  Created member with username={original_username}")

    # Step 2: Try to create another member with the SAME username (should fail)
    payload2 = create_test_member_payload("Player")
    payload2["username"] = original_username  # duplicate!
    unique_email = payload2["email"]

    r2 = admin.post(f"{BASE_URL}/api/members", json=payload2)
    second_succeeded = (r2.status_code == 200 and r2.json().get("success", False))
    print(f"  Second creation (dup username): status={r2.status_code}, success={second_succeeded}")

    # Step 3: Check if an orphan Member row exists
    conn, cur = get_db("olympia_track")
    cur.execute("SELECT MemberID FROM Member WHERE Email = %s", (unique_email,))
    orphan = cur.fetchone()
    close_db(conn, cur)

    if orphan:
        # Check if the user row exists for this member
        conn2, cur2 = get_db("olympia_auth")
        cur2.execute("SELECT user_id FROM users WHERE member_id = %s", (orphan["MemberID"],))
        user_row = cur2.fetchone()
        close_db(conn2, cur2)
        has_orphan = user_row is None
    else:
        has_orphan = False

    # Atomicity is preserved if there's no orphan
    passed = not has_orphan
    if has_orphan:
        print(f"  ATOMICITY VIOLATION: Member row exists (ID={orphan['MemberID']}) but no users row!")
    else:
        print(f"  Atomicity preserved: no orphan Member rows")

    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] Atomicity: Cross-DB Member Creation")
    return {
        "test": "Atomicity: Cross-DB Member Creation",
        "passed": passed,
        "has_orphan": has_orphan,
        "orphan_member_id": orphan["MemberID"] if orphan and has_orphan else None,
    }


# ── Consistency: Invariant checks ─────────────────────────────────────────

def test_consistency_invariants():
    """After concurrent operations, verify all DB invariants hold."""
    _banner("ACID - Consistency: Invariant Checks")

    checks = {}

    # Equipment: issued <= total
    conn, cur = get_db("olympia_track")
    cur.execute("""
        SELECT e.EquipmentID, e.TotalQuantity,
               COALESCE(SUM(ei.Quantity), 0) AS issued
        FROM Equipment e
        LEFT JOIN EquipmentIssue ei
               ON e.EquipmentID = ei.EquipmentID AND ei.ReturnDate IS NULL
        GROUP BY e.EquipmentID, e.TotalQuantity
        HAVING issued > e.TotalQuantity
    """)
    equip_violations = cur.fetchall()
    checks["equipment_qty"] = len(equip_violations) == 0
    print(f"  Equipment qty invariant: {'PASS' if checks['equipment_qty'] else 'FAIL'} ({len(equip_violations)} violations)")

    # No duplicate registrations
    cur.execute("""
        SELECT TournamentID, TeamID, COUNT(*) AS cnt
        FROM TournamentRegistration
        GROUP BY TournamentID, TeamID HAVING cnt > 1
    """)
    dup_regs = cur.fetchall()
    checks["no_dup_registrations"] = len(dup_regs) == 0
    print(f"  No duplicate registrations: {'PASS' if checks['no_dup_registrations'] else 'FAIL'} ({len(dup_regs)} dupes)")

    # No negative quantities
    cur.execute("SELECT COUNT(*) AS cnt FROM Equipment WHERE TotalQuantity < 0")
    neg_equip = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM EquipmentIssue WHERE Quantity < 0")
    neg_issues = cur.fetchone()["cnt"]
    checks["no_negatives"] = (neg_equip == 0 and neg_issues == 0)
    print(f"  No negative quantities: {'PASS' if checks['no_negatives'] else 'FAIL'}")

    close_db(conn, cur)

    passed = all(checks.values())
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] Consistency: Invariant Checks")
    return {
        "test": "Consistency: Invariant Checks",
        "passed": passed,
        "checks": checks,
    }


# ── Isolation: No dirty reads ─────────────────────────────────────────────

def test_isolation_no_dirty_reads():
    """Thread A issues equipment inside a transaction (uncommitted).
    Thread B reads availability — must see OLD value, not the uncommitted change.
    """
    _banner("ACID - Isolation: No Dirty Reads")

    admin = admin_session()
    coach = coach_session()
    coach_mid = get_coach_member_id(coach)

    # Create test member and equipment
    member_payload = create_test_member_payload("Player")
    r = admin.post(f"{BASE_URL}/api/members", json=member_payload)
    r.raise_for_status()
    player_mid = r.json()["data"]["member_id"]

    team_id = create_test_team(admin, coach_mid)
    admin.post(f"{BASE_URL}/api/teams/{team_id}/members", json={"member_id": player_mid, "role": "Player"})

    equip_id = create_test_equipment(admin, total_qty=10)

    # Read initial availability
    r = coach.get(f"{BASE_URL}/api/equipment/{equip_id}")
    initial_available = r.json()["data"]["AvailableQuantity"]
    print(f"  Initial availability: {initial_available}")

    # Thread A: start a DB transaction, issue equipment, hold it open
    barrier = threading.Barrier(2, timeout=10)
    commit_event = threading.Event()
    thread_a_result = {}
    thread_b_reads = []

    def thread_a_work():
        """Direct DB transaction: issue equipment but delay commit."""
        import mysql.connector
        from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD
        conn = mysql.connector.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
            database="olympia_track",
        )
        conn.autocommit = False
        cur = conn.cursor(dictionary=True)
        try:
            # Lock and issue
            cur.execute(
                "SELECT e.TotalQuantity, COALESCE(SUM(ei.Quantity),0) AS issued "
                "FROM Equipment e LEFT JOIN EquipmentIssue ei "
                "ON e.EquipmentID=ei.EquipmentID AND ei.ReturnDate IS NULL "
                "WHERE e.EquipmentID=%s GROUP BY e.TotalQuantity FOR UPDATE",
                (equip_id,),
            )
            cur.fetchone()
            # Get next IssueID
            cur.execute("SELECT COALESCE(MAX(IssueID),0)+1 AS nid FROM EquipmentIssue")
            nid = cur.fetchone()["nid"]
            cur.execute(
                "INSERT INTO EquipmentIssue (IssueID, EquipmentID, MemberID, IssueDate, Quantity) "
                "VALUES (%s,%s,%s,'2025-01-20',3)",
                (nid, equip_id, player_mid),
            )
            thread_a_result["issued"] = True
            # Signal thread B to read
            barrier.wait()
            # Wait for signal to commit
            commit_event.wait(timeout=10)
            conn.commit()
            thread_a_result["committed"] = True
        except Exception as e:
            conn.rollback()
            thread_a_result["error"] = str(e)
        finally:
            cur.close()
            conn.close()

    def thread_b_work():
        """Read availability via API while thread A's transaction is open."""
        barrier.wait()
        time.sleep(0.3)  # small delay to ensure A's INSERT is done but uncommitted
        r = coach.get(f"{BASE_URL}/api/equipment/{equip_id}")
        avail = r.json()["data"]["AvailableQuantity"]
        thread_b_reads.append(("before_commit", avail))

    ta = threading.Thread(target=thread_a_work)
    tb = threading.Thread(target=thread_b_work)
    ta.start()
    tb.start()
    tb.join(timeout=15)

    # Now tell A to commit
    commit_event.set()
    ta.join(timeout=15)

    # Read after commit
    r = coach.get(f"{BASE_URL}/api/equipment/{equip_id}")
    after_avail = r.json()["data"]["AvailableQuantity"]
    thread_b_reads.append(("after_commit", after_avail))

    print(f"  Thread B reads: {thread_b_reads}")
    print(f"  Thread A: issued={thread_a_result.get('issued')}, committed={thread_a_result.get('committed')}")

    # Before commit, Thread B should see the original availability
    before_read = [v for label, v in thread_b_reads if label == "before_commit"]
    no_dirty_read = all(v == initial_available for v in before_read)

    passed = no_dirty_read
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] Isolation: No Dirty Reads")
    return {
        "test": "Isolation: No Dirty Reads",
        "passed": passed,
        "initial_available": initial_available,
        "reads_before_commit": before_read,
        "after_commit": after_avail,
    }


# ── Isolation: No intermediate states ──────────────────────────────────────

def test_isolation_valid_states():
    """Run N concurrent issues + reads. Every observed availability must be a valid state."""
    _banner("ACID - Isolation: Valid States Only")

    admin = admin_session()
    coach = coach_session()
    coach_mid = get_coach_member_id(coach)

    member_payload = create_test_member_payload("Player")
    r = admin.post(f"{BASE_URL}/api/members", json=member_payload)
    r.raise_for_status()
    player_mid = r.json()["data"]["member_id"]

    team_id = create_test_team(admin, coach_mid)
    admin.post(f"{BASE_URL}/api/teams/{team_id}/members", json={"member_id": player_mid, "role": "Player"})

    total_qty = 10
    equip_id = create_test_equipment(admin, total_qty=total_qty)

    observed_values = []
    issue_count = 8

    def issue_one(i):
        s = coach_session()
        payload = {
            "equipment_id": equip_id,
            "member_id": player_mid,
            "issue_date": "2025-01-15",
            "quantity": 1,
        }
        return s.post(f"{BASE_URL}/api/equipment/issue", json=payload)

    def read_one(i):
        s = coach_session()
        r = s.get(f"{BASE_URL}/api/equipment/{equip_id}")
        if r.status_code == 200:
            observed_values.append(r.json()["data"]["AvailableQuantity"])

    with ThreadPoolExecutor(max_workers=16) as pool:
        # Interleave issues and reads
        futures = []
        for i in range(issue_count):
            futures.append(pool.submit(issue_one, i))
            futures.append(pool.submit(read_one, i))
        # Additional reads
        for i in range(5):
            futures.append(pool.submit(read_one, i + issue_count))
        for f in as_completed(futures):
            f.result()  # propagate exceptions

    # Valid values: 0 to total_qty, integers only
    valid = all(isinstance(v, int) and 0 <= v <= total_qty for v in observed_values)
    print(f"  Observed availability values: {sorted(set(observed_values))}")
    print(f"  All values valid (0..{total_qty}): {valid}")

    status = "PASS" if valid else "FAIL"
    print(f"  [{status}] Isolation: Valid States Only")
    return {
        "test": "Isolation: Valid States Only",
        "passed": valid,
        "observed_values": sorted(set(observed_values)),
    }


# ── Durability: Data persists after restart ────────────────────────────────

def test_durability():
    """Create data, verify it persists (no restart needed — just verify committed data is readable)."""
    _banner("ACID - Durability: Committed Data Persistence")

    admin = admin_session()

    # Create a member and remember its details
    payload = create_test_member_payload("Player")
    r = admin.post(f"{BASE_URL}/api/members", json=payload)
    r.raise_for_status()
    member_id = r.json()["data"]["member_id"]
    expected_email = payload["email"]
    print(f"  Created member ID={member_id}, email={expected_email}")

    # Verify via direct DB query
    conn, cur = get_db("olympia_track")
    cur.execute("SELECT Email FROM Member WHERE MemberID = %s", (member_id,))
    row = cur.fetchone()
    close_db(conn, cur)

    db_email = row["Email"] if row else None
    passed = (db_email == expected_email)
    print(f"  DB query: email={db_email}")

    # Also verify via API
    r2 = admin.get(f"{BASE_URL}/api/members/{member_id}")
    api_email = r2.json()["data"]["Email"] if r2.status_code == 200 else None
    api_match = (api_email == expected_email)
    print(f"  API query: email={api_email}")

    passed = passed and api_match
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] Durability: Committed Data Persistence")
    return {
        "test": "Durability: Committed Data Persistence",
        "passed": passed,
        "member_id": member_id,
        "expected_email": expected_email,
        "db_email": db_email,
        "api_email": api_email,
    }


# ── Main ───────────────────────────────────────────────────────────────────

def run_all():
    results = []
    tests = [
        test_atomicity_cross_db,
        test_consistency_invariants,
        test_isolation_no_dirty_reads,
        test_isolation_valid_states,
        test_durability,
    ]
    for test_fn in tests:
        try:
            results.append(test_fn())
        except Exception as e:
            print(f"  [ERROR] {test_fn.__name__}: {e}")
            results.append({"test": test_fn.__name__, "passed": False, "error": str(e)})
    return results


if __name__ == "__main__":
    run_all()
