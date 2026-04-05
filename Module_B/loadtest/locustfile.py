"""Locust stress test with three user types matching RBAC roles.

Run:
    locust -f locustfile.py --host=http://localhost:8000
    # or headless:
    locust -f locustfile.py --host=http://localhost:8000 --headless -u 50 -r 10 -t 2m

Shared fixture IDs (injected via env vars by test_stress.py before launching locust):
    STRESS_EQUIP_ID        — EquipmentID all CoachUsers hammer for issue_equipment
    STRESS_TOURNAMENT_ID   — TournamentID all CoachUsers race to register for
    STRESS_TEAM_ID         — TeamID used for tournament registration
    STRESS_PLAYER_ID       — MemberID used as the equipment issue target
"""

import os
import random
import string
from locust import HttpUser, task, between, events
from config import ADMIN_CREDS, COACH_CREDS, PLAYER_CREDS


def _rand(n=6):
    return "".join(random.choices(string.ascii_lowercase, k=n))


class _AuthMixin:
    """Login on start and store cookies."""

    username = ""
    password = ""

    def on_start(self):
        resp = self.client.post("/auth/login", json={
            "username": self.username,
            "password": self.password,
        })
        if resp.status_code != 200:
            raise Exception(f"Login failed for {self.username}: {resp.text}")


class AdminUser(_AuthMixin, HttpUser):
    weight = 1
    wait_time = between(1, 3)
    username = ADMIN_CREDS["username"]
    password = ADMIN_CREDS["password"]

    @task(5)
    def list_members(self):
        self.client.get("/api/members", name="/api/members [GET]")

    @task(3)
    def list_equipment(self):
        self.client.get("/api/equipment", name="/api/equipment [GET]")

    @task(2)
    def list_tournaments(self):
        self.client.get("/api/tournaments", name="/api/tournaments [GET]")

    @task(1)
    def view_audit_log(self):
        self.client.get("/admin/audit-log", name="/admin/audit-log [GET]")

    @task(1)
    def create_equipment(self):
        payload = {
            "equipment_name": f"LocustEquip_{_rand()}",
            "total_quantity": random.randint(5, 50),
            "equipment_condition": random.choice(["New", "Good", "Fair"]),
        }
        self.client.post("/api/equipment", json=payload, name="/api/equipment [POST]")

    @task(1)
    def create_tournament(self):
        payload = {
            "tournament_name": f"LocustTourney_{_rand()}",
            "start_date": "2025-08-01",
            "end_date": "2025-08-10",
            "status": "Upcoming",
        }
        self.client.post("/api/tournaments", json=payload, name="/api/tournaments [POST]")


class CoachUser(_AuthMixin, HttpUser):
    weight = 3
    wait_time = between(1, 3)
    username = COACH_CREDS["username"]
    password = COACH_CREDS["password"]

    def on_start(self):
        super().on_start()
        # Read shared fixture IDs injected by test_stress.py via env vars.
        # Default to 0 when running locust standalone (no stress fixtures).
        self._equip_id   = int(os.environ.get("STRESS_EQUIP_ID",       0) or 0)
        self._tourney_id = int(os.environ.get("STRESS_TOURNAMENT_ID",  0) or 0)
        self._team_id    = int(os.environ.get("STRESS_TEAM_ID",        0) or 0)
        self._player_id  = int(os.environ.get("STRESS_PLAYER_ID",      0) or 0)

    @task(5)
    def list_teams(self):
        self.client.get("/api/teams", name="/api/teams [GET]")

    @task(3)
    def list_equipment(self):
        self.client.get("/api/equipment", name="/api/equipment [GET]")

    @task(2)
    def list_events(self):
        self.client.get("/api/events", name="/api/events [GET]")

    @task(2)
    def list_equipment_issues(self):
        self.client.get("/api/equipment/issues", name="/api/equipment/issues [GET]")

    @task(1)
    def list_performance_logs(self):
        self.client.get("/api/performance-logs", name="/api/performance-logs [GET]")

    @task(2)
    def issue_equipment(self):
        """Contested write: many coaches issue qty=1 from the same equipment.
        Tests isolation — DB must enforce issued <= total under concurrent load."""
        if not self._equip_id or not self._player_id:
            return
        self.client.post(
            "/api/equipment/issue",
            json={
                "equipment_id": self._equip_id,
                "member_id":    self._player_id,
                "issue_date":   "2025-08-01",
                "quantity":     1,
            },
            name="/api/equipment/issue [POST]",
        )

    @task(1)
    def register_tournament(self):
        """Contested write: all coaches race to register the same team for the same tournament.
        Tests isolation — only one registration per (tournament, team) must survive."""
        if not self._tourney_id or not self._team_id:
            return
        self.client.post(
            f"/api/registrations/tournament/{self._tourney_id}/team/{self._team_id}",
            name="/api/registrations [POST]",
        )


class PlayerUser(_AuthMixin, HttpUser):
    weight = 6
    wait_time = between(1, 3)
    username = PLAYER_CREDS["username"]
    password = PLAYER_CREDS["password"]

    @task(5)
    def view_profile(self):
        self.client.get("/auth/isAuth", name="/auth/isAuth [GET]")

    @task(3)
    def list_events(self):
        self.client.get("/api/events", name="/api/events [GET]")

    @task(3)
    def list_equipment(self):
        self.client.get("/api/equipment", name="/api/equipment [GET]")

    @task(2)
    def list_tournaments(self):
        self.client.get("/api/tournaments", name="/api/tournaments [GET]")

    @task(1)
    def list_members(self):
        self.client.get("/api/members", name="/api/members [GET]")
