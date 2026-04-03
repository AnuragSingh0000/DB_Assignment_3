"""Central configuration for load tests."""

import os
from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _default_db_healthcheck(host: str, port: int, user: str, password: str) -> str:
    return (
        f"mysqladmin -h {host} -P {port} "
        f"-u {user} -p{password} ping"
    )

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")
TEST_API_PORT = _env_int("TEST_API_PORT", 8001)

# Credentials for each role (must exist in the database)
ADMIN_CREDS  = {"username": os.getenv("ADMIN_USERNAME",  "amit_admin"),   "password": os.getenv("ADMIN_PASSWORD",  "password123")}
COACH_CREDS  = {"username": os.getenv("COACH_USERNAME",  "sunita_coach"), "password": os.getenv("COACH_PASSWORD",  "password123")}
PLAYER_CREDS = {"username": os.getenv("PLAYER_USERNAME", "meera_player"), "password": os.getenv("PLAYER_PASSWORD", "password123")}

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = _env_int("DB_PORT", 3306)
DB_USER     = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

DB_AUTH  = "olympia_auth"
DB_TRACK = "olympia_track"

# Pool / concurrency knobs
THREAD_COUNT     = 20
EQUIPMENT_QTY    = 5
REGISTRATION_DUP = 10
REQUEST_TIMEOUT  = _env_int("REQUEST_TIMEOUT", 15)
DB_POOL_SIZE     = _env_int("DB_POOL_SIZE", 32)
FAILURE_DB_POOL_SIZE = _env_int("FAILURE_DB_POOL_SIZE", 5)

TEST_DB_RESTART_CMD = os.getenv("TEST_DB_RESTART_CMD", "")
TEST_DB_HEALTHCHECK_CMD = os.getenv(
    "TEST_DB_HEALTHCHECK_CMD",
    _default_db_healthcheck(DB_HOST, DB_PORT, DB_USER, DB_PASSWORD),
)

LOCUST_USERS = _env_int("LOCUST_USERS", 100)
LOCUST_SPAWN_RATE = _env_int("LOCUST_SPAWN_RATE", 20)
LOCUST_DURATION = os.getenv("LOCUST_DURATION", "2m")
LOCUST_MAX_FAILURE_RATE = float(os.getenv("LOCUST_MAX_FAILURE_RATE", "5"))
LOCUST_MAX_P95_MS = float(os.getenv("LOCUST_MAX_P95_MS", "2000"))
