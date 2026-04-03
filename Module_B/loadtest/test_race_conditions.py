"""Race Condition Tests: equipment issue, tournament registration, ID generation."""

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from helpers import (
    admin_session, coach_session, get_db, close_db,
    create_test_equipment, create_test_member_payload,
    create_test_tournament, create_test_team, get_coach_member_id,
)
from config import BASE_URL, THREAD_COUNT, EQUIPMENT_QTY


def _banner(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


# ── RC-1: Equipment Issue Race ─────────────────────────────────────────────

def test_equipment_issue_race():
    """20 threads each try to issue qty=1 from equipment with TotalQuantity=5.
    Expect exactly 5 succeed, 15 fail.
    """
    _banner("RC-1: Equipment Issue Race")

    admin = admin_session()
    coach = coach_session()
    coach_mid = get_coach_member_id(coach)

    # Create a player member that the coach manages
    member_payload = create_test_member_payload("Player")
    r = admin.post(f"{BASE_URL}/api/members", json=member_payload)
    r.raise_for_status()
    player_mid = r.json()["data"]["member_id"]

    # Assign the player to a team under this coach
    team_id = create_test_team(admin, coach_mid)
    admin.post(f"{BASE_URL}/api/teams/{team_id}/members", json={"member_id": player_mid, "role": "Player"})

    # Create equipment with limited stock
    equip_id = create_test_equipment(admin, total_qty=EQUIPMENT_QTY)
    print(f"  Equipment ID={equip_id}, TotalQty={EQUIPMENT_QTY}")
    print(f"  Launching {THREAD_COUNT} concurrent issue requests...")

    results = {"success": 0, "fail": 0, "errors": []}

    def issue_one(thread_id):
        # Each thread gets its own session
        s = coach_session()
        payload = {
            "equipment_id": equip_id,
            "member_id": player_mid,
            "issue_date": "2025-01-15",
            "quantity": 1,
        }
        resp = s.post(f"{BASE_URL}/api/equipment/issue", json=payload)
        return resp.status_code, resp.json()

    with ThreadPoolExecutor(max_workers=THREAD_COUNT) as pool:
        futures = {pool.submit(issue_one, i): i for i in range(THREAD_COUNT)}
        for f in as_completed(futures):
            code, body = f.result()
            if code == 200 and body.get("success"):
                results["success"] += 1
            else:
                results["fail"] += 1

    # DB verification
    conn, cur = get_db("olympia_track")
    cur.execute(
        "SELECT COALESCE(SUM(Quantity), 0) AS issued "
        "FROM EquipmentIssue WHERE EquipmentID = %s AND ReturnDate IS NULL",
        (equip_id,),
    )
    db_issued = cur.fetchone()["issued"]
    close_db(conn, cur)

    print(f"\n  Results: {results['success']} succeeded, {results['fail']} failed")
    print(f"  DB verification: issued qty = {db_issued} (expected {EQUIPMENT_QTY})")

    passed = (results["success"] == EQUIPMENT_QTY and db_issued == EQUIPMENT_QTY)
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] RC-1: Equipment Issue Race")
    return {
        "test": "RC-1: Equipment Issue Race",
        "passed": passed,
        "success_count": results["success"],
        "fail_count": results["fail"],
        "db_issued": db_issued,
        "expected_issued": EQUIPMENT_QTY,
    }


# ── RC-2: Tournament Registration Race ────────────────────────────────────

def test_registration_race():
    """10 threads register the same team for the same tournament.
    Expect exactly 1 succeeds.
    """
    _banner("RC-2: Tournament Registration Race")

    admin = admin_session()
    coach = coach_session()
    coach_mid = get_coach_member_id(coach)

    tournament_id = create_test_tournament(admin)
    team_id = create_test_team(admin, coach_mid)
    thread_count = 10

    print(f"  Tournament={tournament_id}, Team={team_id}")
    print(f"  Launching {thread_count} concurrent registration requests...")

    results = {"success": 0, "fail": 0}

    def register_one(tid):
        s = coach_session()
        resp = s.post(
            f"{BASE_URL}/api/registrations/tournament/{tournament_id}/team/{team_id}",
        )
        return resp.status_code, resp.json()

    with ThreadPoolExecutor(max_workers=thread_count) as pool:
        futures = {pool.submit(register_one, i): i for i in range(thread_count)}
        for f in as_completed(futures):
            code, body = f.result()
            if code == 200 and body.get("success"):
                results["success"] += 1
            else:
                results["fail"] += 1

    # DB verification
    conn, cur = get_db("olympia_track")
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM TournamentRegistration "
        "WHERE TournamentID = %s AND TeamID = %s",
        (tournament_id, team_id),
    )
    db_count = cur.fetchone()["cnt"]
    close_db(conn, cur)

    print(f"\n  Results: {results['success']} succeeded, {results['fail']} failed")
    print(f"  DB verification: registration count = {db_count} (expected 1)")

    passed = (results["success"] == 1 and db_count == 1)
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] RC-2: Tournament Registration Race")
    return {
        "test": "RC-2: Tournament Registration Race",
        "passed": passed,
        "success_count": results["success"],
        "fail_count": results["fail"],
        "db_count": db_count,
    }


# ── RC-3: Concurrent ID Generation ────────────────────────────────────────

def test_id_generation_race():
    """20 concurrent member creation requests — no duplicate MemberIDs."""
    _banner("RC-3: Concurrent ID Generation")

    thread_count = THREAD_COUNT
    print(f"  Launching {thread_count} concurrent member creation requests...")

    results = {"success": 0, "fail": 0, "member_ids": []}

    def create_one(tid):
        s = admin_session()
        payload = create_test_member_payload("Player")
        resp = s.post(f"{BASE_URL}/api/members", json=payload)
        return resp.status_code, resp.json()

    with ThreadPoolExecutor(max_workers=thread_count) as pool:
        futures = {pool.submit(create_one, i): i for i in range(thread_count)}
        for f in as_completed(futures):
            code, body = f.result()
            if code == 200 and body.get("success"):
                results["success"] += 1
                mid = body.get("data", {}).get("member_id")
                if mid:
                    results["member_ids"].append(mid)
            else:
                results["fail"] += 1

    # DB verification: no duplicate MemberIDs
    conn, cur = get_db("olympia_track")
    cur.execute(
        "SELECT MemberID, COUNT(*) AS cnt FROM Member "
        "GROUP BY MemberID HAVING cnt > 1"
    )
    dupes = cur.fetchall()
    close_db(conn, cur)

    total_accounted = results["success"] + results["fail"]
    print(f"\n  Results: {results['success']} succeeded, {results['fail']} failed")
    print(f"  Total accounted: {total_accounted}/{thread_count}")
    print(f"  Duplicate MemberIDs in DB: {len(dupes)}")

    passed = (len(dupes) == 0 and total_accounted == thread_count)
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] RC-3: Concurrent ID Generation")
    return {
        "test": "RC-3: Concurrent ID Generation",
        "passed": passed,
        "success_count": results["success"],
        "fail_count": results["fail"],
        "duplicates": len(dupes),
        "total_accounted": total_accounted,
    }


# ── Main ───────────────────────────────────────────────────────────────────

def run_all():
    results = []
    for test_fn in [test_equipment_issue_race, test_registration_race, test_id_generation_race]:
        try:
            results.append(test_fn())
        except Exception as e:
            print(f"  [ERROR] {test_fn.__name__}: {e}")
            results.append({"test": test_fn.__name__, "passed": False, "error": str(e)})
    return results


if __name__ == "__main__":
    run_all()
