from __future__ import annotations
import hashlib
import mysql.connector
from app.config import DB_CONFIG_TRACK


def _is_duplicate_key_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "duplicate" in message and ("primary" in message or "unique" in message or "for key" in message)


def _lock_name(next_id_sql: str) -> str:
    digest = hashlib.sha1(next_id_sql.encode("utf-8")).hexdigest()[:16]
    return f"idgen:{digest}"


def _fresh_track_connection():
    conn = mysql.connector.connect(**DB_CONFIG_TRACK)
    conn.autocommit = True
    return conn


def insert_with_generated_id(
    track_db,
    *,
    requested_id: int | None,
    next_id_sql: str,
    next_id_key: str = "nid",
    insert_fn,
    max_attempts: int = 3,
) -> int:
    if requested_id is not None:
        insert_fn(requested_id)
        return requested_id
    last_exc: Exception | None = None
    lock_name = _lock_name(next_id_sql)
    lock_conn = _fresh_track_connection()
    lock_db = lock_conn.cursor(dictionary=True)
    try:
        lock_db.execute("SELECT GET_LOCK(%s, %s) AS acquired", (lock_name, 10))
        lock_row = lock_db.fetchone()
        if not lock_row or lock_row.get("acquired") != 1:
            raise RuntimeError(f"Could not acquire ID-generation lock: {lock_name}")
        for _ in range(max_attempts):
            lock_db.execute(next_id_sql)
            generated_id = lock_db.fetchone()[next_id_key]
            try:
                insert_fn(generated_id)
                return generated_id
            except Exception as exc:
                last_exc = exc
                if not _is_duplicate_key_error(exc):
                    raise
    finally:
        try:
            lock_db.execute("SELECT RELEASE_LOCK(%s) AS released", (lock_name,))
            lock_db.fetchone()
        except Exception:
            pass
        lock_db.close()
        lock_conn.close()
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Failed to generate an ID for insert.")
