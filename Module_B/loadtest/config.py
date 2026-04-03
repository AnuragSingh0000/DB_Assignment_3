"""Central configuration for load tests."""

import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")

# Credentials for each role (must exist in the database)
ADMIN_CREDS  = {"username": "admin",  "password": os.getenv("ADMIN_PASSWORD",  "admin123")}
COACH_CREDS  = {"username": "coach1", "password": os.getenv("COACH_PASSWORD",  "coach123")}
PLAYER_CREDS = {"username": "player1","password": os.getenv("PLAYER_PASSWORD", "player123")}

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", 3306))
DB_USER     = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

DB_AUTH  = "olympia_auth"
DB_TRACK = "olympia_track"

# Pool / concurrency knobs
THREAD_COUNT     = 20
EQUIPMENT_QTY    = 5
REGISTRATION_DUP = 10
