"""Post-test database consistency checker.

Run standalone:  python verify.py
Or import:       from verify import run_all_checks
"""

import sys
from helpers import get_db, close_db
from config import BASE_URL
import requests


def _check(label: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    return ok


def check_equipment_invariant() -> bool:
    """Issued qty must never exceed total qty for any equipment."""
    conn, cur = get_db("olympia_track")
    cur.execute("""
        SELECT e.EquipmentID, e.EquipmentName, e.TotalQuantity,
               COALESCE(SUM(ei.Quantity), 0) AS issued
        FROM Equipment e
        LEFT JOIN EquipmentIssue ei
               ON e.EquipmentID = ei.EquipmentID AND ei.ReturnDate IS NULL
        GROUP BY e.EquipmentID, e.EquipmentName, e.TotalQuantity
        HAVING issued > e.TotalQuantity
    """)
    violations = cur.fetchall()
    close_db(conn, cur)
    return _check(
        "Equipment: issued <= total",
        len(violations) == 0,
        f"{len(violations)} violation(s)" if violations else "",
    )


def check_no_duplicate_registrations() -> bool:
    """No (TournamentID, TeamID) pair should appear more than once."""
    conn, cur = get_db("olympia_track")
    cur.execute("""
        SELECT TournamentID, TeamID, COUNT(*) AS cnt
        FROM TournamentRegistration
        GROUP BY TournamentID, TeamID
        HAVING cnt > 1
    """)
    dupes = cur.fetchall()
    close_db(conn, cur)
    return _check(
        "Registration: no duplicates",
        len(dupes) == 0,
        f"{len(dupes)} duplicate(s)" if dupes else "",
    )


def check_no_duplicate_member_ids() -> bool:
    """Every MemberID in the Member table must be unique."""
    conn, cur = get_db("olympia_track")
    cur.execute("""
        SELECT MemberID, COUNT(*) AS cnt
        FROM Member
        GROUP BY MemberID
        HAVING cnt > 1
    """)
    dupes = cur.fetchall()
    close_db(conn, cur)
    return _check(
        "Members: no duplicate IDs",
        len(dupes) == 0,
        f"{len(dupes)} duplicate(s)" if dupes else "",
    )


def check_cross_db_consistency() -> bool:
    """Every users.member_id must have a matching Member row."""
    conn, cur = get_db("olympia_auth")
    cur.execute("""
        SELECT u.user_id, u.username, u.member_id
        FROM users u
        LEFT JOIN olympia_track.Member m ON u.member_id = m.MemberID
        WHERE u.member_id IS NOT NULL AND m.MemberID IS NULL
    """)
    orphans = cur.fetchall()
    close_db(conn, cur)
    return _check(
        "Cross-DB: no orphan users",
        len(orphans) == 0,
        f"{len(orphans)} orphan(s)" if orphans else "",
    )


def check_no_negative_quantities() -> bool:
    """No equipment should have negative TotalQuantity or negative issue Quantity."""
    conn, cur = get_db("olympia_track")
    cur.execute("SELECT COUNT(*) AS cnt FROM Equipment WHERE TotalQuantity < 0")
    neg_equip = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM EquipmentIssue WHERE Quantity < 0")
    neg_issue = cur.fetchone()["cnt"]
    close_db(conn, cur)
    return _check(
        "No negative quantities",
        neg_equip == 0 and neg_issue == 0,
        f"equipment={neg_equip}, issues={neg_issue}",
    )


def check_no_orphan_member_rows() -> bool:
    """Members without corresponding users row (atomicity check)."""
    conn, cur = get_db("olympia_track")
    cur.execute("""
        SELECT m.MemberID, m.Name
        FROM Member m
        LEFT JOIN olympia_auth.users u ON m.MemberID = u.member_id
        WHERE u.user_id IS NULL
    """)
    orphans = cur.fetchall()
    close_db(conn, cur)
    return _check(
        "Atomicity: no orphan Member rows",
        len(orphans) == 0,
        f"{len(orphans)} orphan(s): {[o['MemberID'] for o in orphans[:5]]}" if orphans else "",
    )


def run_all_checks() -> dict:
    """Run every check, return dict of {name: passed}."""
    print("\n=== Database Consistency Verification ===\n")
    results = {
        "equipment_invariant": check_equipment_invariant(),
        "no_duplicate_registrations": check_no_duplicate_registrations(),
        "no_duplicate_member_ids": check_no_duplicate_member_ids(),
        "cross_db_consistency": check_cross_db_consistency(),
        "no_negative_quantities": check_no_negative_quantities(),
        "no_orphan_members": check_no_orphan_member_rows(),
    }
    total = len(results)
    passed = sum(results.values())
    print(f"\n  {passed}/{total} checks passed.\n")
    return results


if __name__ == "__main__":
    results = run_all_checks()
    sys.exit(0 if all(results.values()) else 1)
