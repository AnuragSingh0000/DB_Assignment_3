import os
from dotenv import load_dotenv

env_path = ".env.example"

load_dotenv()

DB_CONFIG_AUTH = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": "olympia_auth",
}

DB_CONFIG_TRACK = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": "olympia_track",
}

JWT_SECRET       = os.getenv("JWT_SECRET", "change-me")

JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", 8))

ALGORITHM        = "HS256"

SECURE_COOKIES   = os.getenv("SECURE_COOKIES", "false").lower() == "true"

ACCESS_TOKEN_EXPIRY_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRY_MINUTES", 15))
