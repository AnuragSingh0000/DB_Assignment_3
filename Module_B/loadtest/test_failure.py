"""Failure Simulation Tests: connection kill, pool exhaustion, server crash."""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from helpers import (
    admin_session, coach_session, get_db, close_db,
    create_test_equipment, create_test_member_payload,
    get_coach_member_id, create_test_team, add_member_to_team,
)
from config import BASE_URL, DB_HOST, DB_PORT, DB_POOL_SIZE, DB_USER, DB_PASSWORD, REQUEST_TIMEOUT
from progress import ProgressBar, print_phase_progress
from harness import get_active_harness
import mysql.connector


def _banner(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


# ── FS-1: Connection Kill ──────────────────────────────────────────────────

def test_connection_kill():
    """Start member creation requests while killing MySQL connections.
    No partial records should exist.
    """
    _banner("FS-1: Connection Kill During Operations")

    admin = admin_session()
    kill_count = 0
    stop_killing = threading.Event()

    def connection_killer():
        """Periodically kill active connections to olympia_track."""
        nonlocal kill_count
        conn = mysql.connector.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        )
        cur = conn.cursor(dictionary=True)
        while not stop_killing.is_set():
            try:
                cur.execute("SHOW PROCESSLIST")
                procs = cur.fetchall()
                for p in procs:
                    if p.get("db") in ("olympia_track", "olympia_auth") and p["Id"] != conn.connection_id:
                        if p.get("Command") != "Sleep":
                            try:
                                cur.execute(f"KILL {p['Id']}")
                                kill_count += 1
                            except Exception:
                                pass
            except Exception:
                pass
            time.sleep(0.1)
        cur.close()
        conn.close()

    results = {"success": 0, "fail": 0}

    def create_member(i):
        s = admin_session()
        payload = create_test_member_payload("Player")
        try:
            r = s.post(f"{BASE_URL}/api/members", json=payload)
            return r.status_code, payload["email"]
        except Exception as e:
            return 0, payload["email"]

    # Start the killer thread
    killer = threading.Thread(target=connection_killer, daemon=True)
    killer.start()

    # Run member creations
    thread_count = 15
    print(f"  Launching {thread_count} member creations while killing connections...")

    emails_attempted = []
    with ThreadPoolExecutor(max_workers=thread_count) as pool:
        futures = {pool.submit(create_member, i): i for i in range(thread_count)}
        progress = ProgressBar(thread_count, "Member creations")
        for f in as_completed(futures):
            code, email = f.result()
            emails_attempted.append(email)
            if code == 200:
                results["success"] += 1
            else:
                results["fail"] += 1
            progress.advance(detail=f"ok={results['success']} fail={results['fail']} killed={kill_count}")
        progress.finish(detail=f"ok={results['success']} fail={results['fail']} killed={kill_count}")

    stop_killing.set()
    killer.join(timeout=5)

    print(f"  Results: {results['success']} succeeded, {results['fail']} failed")
    print(f"  Connections killed: {kill_count}")

    # Verify: no partial records (Member without User)
    conn, cur = get_db("olympia_track")
    cur.execute("""
        SELECT m.MemberID, m.Email FROM Member m
        LEFT JOIN olympia_auth.users u ON m.MemberID = u.member_id
        WHERE u.user_id IS NULL
    """)
    orphans = cur.fetchall()
    # Filter only our test emails
    test_orphans = [o for o in orphans if o["Email"] in emails_attempted]
    close_db(conn, cur)

    passed = len(test_orphans) == 0
    print(f"  Orphan member rows (our tests): {len(test_orphans)}")
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] FS-1: Connection Kill")
    return {
        "test": "FS-1: Connection Kill",
        "passed": passed,
        "success": results["success"],
        "fail": results["fail"],
        "connections_killed": kill_count,
        "orphans": len(test_orphans),
    }


# ── FS-2: Pool Exhaustion ─────────────────────────────────────────────────

def test_pool_exhaustion():
    """Hold a row lock so blocked requests consume the small app pool under pressure.
    """
    _banner("FS-2: Pool Exhaustion")

    admin = admin_session()
    equip_id = create_test_equipment(admin, total_qty=100)
    coach = coach_session()
    coach_mid = get_coach_member_id(coach)

    member_payload = create_test_member_payload("Player")
    r = admin.post(f"{BASE_URL}/api/members", json=member_payload)
    r.raise_for_status()
    player_mid = r.json()["data"]["member_id"]

    team_id = create_test_team(admin, coach_mid)
    add_member_to_team(admin, team_id, player_mid)

    thread_count = max(DB_POOL_SIZE * 4, DB_POOL_SIZE + 8)
    print(f"  Sending {thread_count} concurrent equipment issue requests (pool size={DB_POOL_SIZE})...")

    results = {"success": 0, "fail": 0, "pool_error": 0}
    lock_conn = mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database="olympia_track",
    )
    lock_conn.autocommit = False
    lock_cur = lock_conn.cursor(dictionary=True)
    lock_cur.execute(
        """
        SELECT e.TotalQuantity, COALESCE(SUM(ei.Quantity), 0) AS issued
        FROM Equipment e
        LEFT JOIN EquipmentIssue ei
               ON e.EquipmentID = ei.EquipmentID AND ei.ReturnDate IS NULL
        WHERE e.EquipmentID = %s
        GROUP BY e.TotalQuantity
        FOR UPDATE
        """,
        (equip_id,),
    )
    lock_cur.fetchone()

    def issue_one(i):
        s = coach_session()
        payload = {
            "equipment_id": equip_id,
            "member_id": player_mid,
            "issue_date": "2025-01-15",
            "quantity": 1,
        }
        try:
            resp = s.post(
                f"{BASE_URL}/api/equipment/issue",
                json=payload,
                timeout=max(REQUEST_TIMEOUT, 10),
            )
            return resp.status_code, resp.text
        except Exception as e:
            return 0, str(e)

    try:
        with ThreadPoolExecutor(max_workers=thread_count) as pool:
            futures = {pool.submit(issue_one, i): i for i in range(thread_count)}
            time.sleep(3)
            lock_conn.commit()
            progress = ProgressBar(thread_count, "Issue requests")
            for f in as_completed(futures):
                code, text = f.result()
                if code == 200:
                    results["success"] += 1
                elif (
                    code == 0
                    or code >= 500
                    or "pool" in text.lower()
                    or "connection" in text.lower()
                    or "timeout" in text.lower()
                ):
                    results["pool_error"] += 1
                    results["fail"] += 1
                else:
                    results["fail"] += 1
                progress.advance(
                    detail=f"ok={results['success']} fail={results['fail']} pool={results['pool_error']}"
                )
            progress.finish(
                detail=f"ok={results['success']} fail={results['fail']} pool={results['pool_error']}"
            )
    finally:
        try:
            lock_cur.close()
        finally:
            lock_conn.close()

    print(f"  Success: {results['success']}, Failed: {results['fail']}, Pool errors: {results['pool_error']}")

    # Verify system recovers
    time.sleep(2)
    r_check = coach.get(f"{BASE_URL}/api/equipment/{equip_id}")
    recovered = r_check.status_code == 200
    print(f"  System recovery check: {'OK' if recovered else 'FAILED'}")

    # Verify no data corruption
    conn, cur = get_db("olympia_track")
    cur.execute(
        "SELECT COALESCE(SUM(Quantity),0) AS issued FROM EquipmentIssue "
        "WHERE EquipmentID=%s AND ReturnDate IS NULL",
        (equip_id,),
    )
    issued = cur.fetchone()["issued"]
    cur.execute("SELECT TotalQuantity FROM Equipment WHERE EquipmentID=%s", (equip_id,))
    total = cur.fetchone()["TotalQuantity"]
    close_db(conn, cur)

    no_corruption = issued <= total
    print(f"  Issued: {issued}, Total: {total}, Invariant: {'OK' if no_corruption else 'VIOLATED'}")

    pressure_observed = (
        results["pool_error"] > 0
        or (results["fail"] > 0 and results["success"] <= DB_POOL_SIZE)
    )
    print(f"  Pressure observed: {'YES' if pressure_observed else 'NO'}")

    passed = recovered and no_corruption and pressure_observed
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] FS-2: Pool Exhaustion")
    return {
        "test": "FS-2: Pool Exhaustion",
        "passed": passed,
        "success": results["success"],
        "fail": results["fail"],
        "pool_errors": results["pool_error"],
        "recovered": recovered,
        "issued": issued,
        "total": total,
    }


# ── FS-3: Full Stack Restart Verification ─────────────────────────────────

def test_full_stack_restart():
    """Restart the API and MySQL, then verify committed data persists and interrupted work does not."""
    _banner("FS-3: Full Stack Restart Verification")
    harness = get_active_harness()
    if harness is None:
        raise RuntimeError("Managed harness is required for full-stack restart verification.")

    admin = admin_session()
    coach = coach_session()
    coach_mid = get_coach_member_id(coach)

    committed_payload = create_test_member_payload("Player")
    committed_resp = admin.post(f"{BASE_URL}/api/members", json=committed_payload, timeout=REQUEST_TIMEOUT)
    committed_resp.raise_for_status()
    committed_member_id = committed_resp.json()["data"]["member_id"]
    print(f"  Committed member created: ID={committed_member_id}")

    blocked_payload = create_test_member_payload("Player")
    blocked_resp = admin.post(f"{BASE_URL}/api/members", json=blocked_payload, timeout=REQUEST_TIMEOUT)
    blocked_resp.raise_for_status()
    blocked_member_id = blocked_resp.json()["data"]["member_id"]
    team_id = create_test_team(admin, coach_mid)
    add_member_to_team(admin, team_id, blocked_member_id)
    equip_id = create_test_equipment(admin, total_qty=1)

    lock_conn = mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database="olympia_track",
    )
    lock_conn.autocommit = False
    lock_cur = lock_conn.cursor(dictionary=True)
    lock_cur.execute(
        """
        SELECT e.TotalQuantity, COALESCE(SUM(ei.Quantity), 0) AS issued
        FROM Equipment e
        LEFT JOIN EquipmentIssue ei
               ON e.EquipmentID = ei.EquipmentID AND ei.ReturnDate IS NULL
        WHERE e.EquipmentID = %s
        GROUP BY e.TotalQuantity
        FOR UPDATE
        """,
        (equip_id,),
    )
    lock_cur.fetchone()

    request_result = {}

    def interrupted_issue():
        session = coach_session()
        payload = {
            "equipment_id": equip_id,
            "member_id": blocked_member_id,
            "issue_date": "2025-01-15",
            "quantity": 1,
        }
        try:
            response = session.post(
                f"{BASE_URL}/api/equipment/issue",
                json=payload,
                timeout=max(REQUEST_TIMEOUT, 10),
            )
            request_result["status_code"] = response.status_code
            request_result["body"] = response.text
        except Exception as exc:
            request_result["error"] = str(exc)

    thread = threading.Thread(target=interrupted_issue, daemon=True)
    thread.start()
    time.sleep(2)

    try:
        harness.restart_stack()
    finally:
        try:
            lock_cur.close()
        except Exception:
            pass
        try:
            lock_conn.close()
        except Exception:
            pass

    thread.join(timeout=max(REQUEST_TIMEOUT, 10))

    verify_admin = admin_session()
    verify_member = verify_admin.get(f"{BASE_URL}/api/members/{committed_member_id}", timeout=REQUEST_TIMEOUT)
    verify_member.raise_for_status()
    committed_email = verify_member.json()["data"]["member"]["Email"]
    committed_persisted = committed_email == committed_payload["email"]

    conn, cur = get_db("olympia_track")
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM EquipmentIssue WHERE EquipmentID=%s AND MemberID=%s",
        (equip_id, blocked_member_id),
    )
    issue_count = cur.fetchone()["cnt"]
    close_db(conn, cur)
    interrupted_failed = request_result.get("status_code") != 200
    no_partial_state = issue_count == 0

    print(f"  Interrupted request result: {request_result}")
    print(f"  Committed member persisted: {'YES' if committed_persisted else 'NO'}")
    print(f"  Interrupted issue rows after restart: {issue_count}")

    passed = committed_persisted and interrupted_failed and no_partial_state
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] FS-3: Full Stack Restart Verification")
    return {
        "test": "FS-3: Full Stack Restart Verification",
        "passed": passed,
        "committed_member_id": committed_member_id,
        "interrupted_request": request_result,
        "issue_count": issue_count,
    }


# ── Main ───────────────────────────────────────────────────────────────────

def run_all():
    results = []
    tests = [test_connection_kill, test_pool_exhaustion, test_full_stack_restart]
    for index, test_fn in enumerate(tests, start=1):
        print_phase_progress(index, len(tests), test_fn.__name__)
        try:
            results.append(test_fn())
        except Exception as e:
            print(f"  [ERROR] {test_fn.__name__}: {e}")
            results.append({"test": test_fn.__name__, "passed": False, "error": str(e)})
    return results


if __name__ == "__main__":
    import os
    from pathlib import Path
    from harness import ManagedHarness
    import config as loadtest_config

    module_b_dir = Path(__file__).resolve().parents[1]
    with ManagedHarness(module_b_dir, port=loadtest_config.TEST_API_PORT, pool_size=loadtest_config.FAILURE_DB_POOL_SIZE) as harness:
        os.environ["TEST_BASE_URL"] = harness.base_url
        # Update the module-level BASE_URL so test functions pick up the managed server URL
        BASE_URL = harness.base_url  # noqa: F811
        run_all()
