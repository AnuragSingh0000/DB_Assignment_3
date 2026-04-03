import os
from dotenv import load_dotenv

env_path = ".env.example"

load_dotenv()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc

DB_CONFIG_AUTH = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     _env_int("DB_PORT", 3306),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": "olympia_auth",
}

DB_CONFIG_TRACK = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     _env_int("DB_PORT", 3306),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": "olympia_track",
}

DB_POOL_SIZE = _env_int("DB_POOL_SIZE", 32)

JWT_SECRET       = os.getenv("JWT_SECRET", "change-me")

JWT_EXPIRY_HOURS = _env_int("JWT_EXPIRY_HOURS", 8)

ALGORITHM        = "HS256"

SECURE_COOKIES   = os.getenv("SECURE_COOKIES", "false").lower() == "true"

ACCESS_TOKEN_EXPIRY_MINUTES = _env_int("ACCESS_TOKEN_EXPIRY_MINUTES", 15)
