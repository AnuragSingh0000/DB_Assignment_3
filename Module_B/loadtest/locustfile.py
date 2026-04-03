"""Locust stress test with three user types matching RBAC roles.

Run:
    locust -f locustfile.py --host=http://localhost:8000
    # or headless:
    locust -f locustfile.py --host=http://localhost:8000 --headless -u 50 -r 10 -t 2m
"""

import random
import string
from locust import HttpUser, task, between, events


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
    username = "admin"
    password = "admin123"

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
    username = "coach1"
    password = "coach123"

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


class PlayerUser(_AuthMixin, HttpUser):
    weight = 6
    wait_time = between(1, 3)
    username = "player1"
    password = "player123"

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
