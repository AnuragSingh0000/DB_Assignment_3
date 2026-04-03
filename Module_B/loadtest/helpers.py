"""Shared helpers: authenticated sessions, DB connections, test data factories."""

import random
import string
import threading
import requests
import mysql.connector
from requests.cookies import cookiejar_from_dict
from config import (
    BASE_URL, ADMIN_CREDS, COACH_CREDS, PLAYER_CREDS,
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_AUTH, DB_TRACK, REQUEST_TIMEOUT,
)

_AUTH_COOKIE_CACHE = {}
_AUTH_COOKIE_LOCK = threading.Lock()


# ── HTTP sessions ──────────────────────────────────────────────────────────

def login_session(creds: dict) -> requests.Session:
    """Return a fresh session preloaded with authenticated cookies."""
    cache_key = tuple(sorted(creds.items()))
    cached_cookies = _AUTH_COOKIE_CACHE.get(cache_key)

    if cached_cookies is None:
        with _AUTH_COOKIE_LOCK:
            cached_cookies = _AUTH_COOKIE_CACHE.get(cache_key)
            if cached_cookies is None:
                seed_session = requests.Session()
                r = seed_session.post(f"{BASE_URL}/auth/login", json=creds, timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
                cached_cookies = requests.utils.dict_from_cookiejar(seed_session.cookies)
                _AUTH_COOKIE_CACHE[cache_key] = cached_cookies

    s = requests.Session()
    s.cookies = cookiejar_from_dict(cached_cookies)
    return s


def admin_session() -> requests.Session:
    return login_session(ADMIN_CREDS)


def coach_session() -> requests.Session:
    return login_session(COACH_CREDS)


def player_session() -> requests.Session:
    return login_session(PLAYER_CREDS)


def clear_session_cache() -> None:
    with _AUTH_COOKIE_LOCK:
        _AUTH_COOKIE_CACHE.clear()


# ── Database connections ───────────────────────────────────────────────────

def get_db(database: str = DB_TRACK):
    """Return (connection, cursor) pair for direct DB verification."""
    conn = mysql.connector.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, database=database,
    )
    return conn, conn.cursor(dictionary=True)


def close_db(conn, cur):
    cur.close()
    conn.close()


# ── Data factories ─────────────────────────────────────────────────────────

def _rand(n=6):
    return "".join(random.choices(string.ascii_lowercase, k=n))


def create_test_equipment(session: requests.Session, total_qty: int = 5) -> int:
    """Create equipment via API and return its EquipmentID."""
    payload = {
        "equipment_name": f"TestEquip_{_rand()}",
        "total_quantity": total_qty,
        "equipment_condition": "New",
    }
    r = session.post(f"{BASE_URL}/api/equipment", json=payload, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()["data"]["equipment_id"]


def create_test_member_payload(role: str = "Player") -> dict:
    """Return a valid member-creation payload with unique fields."""
    tag = _rand(8)
    return {
        "name": f"Test User {tag}",
        "age": 25,
        "email": f"test_{tag}@example.com",
        "contact_number": f"+1{random.randint(1000000000,9999999999)}",
        "gender": "M",
        "role": role,
        "join_date": "2025-01-01",
        "username": f"user_{tag}",
        "password": "Test1234!",
    }


def create_test_tournament(session: requests.Session) -> int:
    """Create a tournament via API and return its TournamentID."""
    payload = {
        "tournament_name": f"TestTourney_{_rand()}",
        "start_date": "2025-06-01",
        "end_date": "2025-06-10",
        "status": "Upcoming",
    }
    r = session.post(f"{BASE_URL}/api/tournaments", json=payload, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()["data"]["tournament_id"]


def create_test_team(session: requests.Session, coach_member_id: int) -> int:
    """Create a team via API and return its TeamID."""
    payload = {
        "team_name": f"TestTeam_{_rand()}",
        "sport_id": 1,
        "formed_date": "2025-01-01",
        "coach_id": coach_member_id,
    }
    r = session.post(f"{BASE_URL}/api/teams", json=payload, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()["data"]["team_id"]


def add_member_to_team(
    session: requests.Session,
    team_id: int,
    member_id: int,
    *,
    position: str | None = None,
) -> None:
    """Add a member using the real team update API."""
    r = session.get(f"{BASE_URL}/api/teams/{team_id}", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    roster = r.json()["data"]["roster"]
    members = []
    already_present = False
    for row in roster:
        existing_member_id = row["MemberID"]
        if existing_member_id == member_id:
            already_present = True
        members.append(
            {
                "member_id": existing_member_id,
                "position": row.get("Position"),
            }
        )
    if not already_present:
        members.append({"member_id": member_id, "position": position})
    update = session.put(
        f"{BASE_URL}/api/teams/{team_id}",
        json={"members": members},
        timeout=REQUEST_TIMEOUT,
    )
    update.raise_for_status()


def get_coach_member_id(session: requests.Session) -> int:
    """Get the member_id of the currently logged-in coach."""
    r = session.get(f"{BASE_URL}/auth/isAuth", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()["data"]["member_id"]
