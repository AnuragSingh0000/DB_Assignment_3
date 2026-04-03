"""Central configuration for load tests."""

import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")

# Credentials for each role (must exist in the database)
ADMIN_CREDS  = {"username": os.getenv("ADMIN_USERNAME",  "amit_admin"),   "password": os.getenv("ADMIN_PASSWORD",  "password123")}
COACH_CREDS  = {"username": os.getenv("COACH_USERNAME",  "sunita_coach"), "password": os.getenv("COACH_PASSWORD",  "password123")}
PLAYER_CREDS = {"username": os.getenv("PLAYER_USERNAME", "meera_player"), "password": os.getenv("PLAYER_PASSWORD", "password123")}

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
REQUEST_TIMEOUT  = int(os.getenv("REQUEST_TIMEOUT", 15))
