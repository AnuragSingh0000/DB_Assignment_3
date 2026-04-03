from __future__ import annotations


def _is_duplicate_key_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "duplicate" in message and ("primary" in message or "unique" in message or "for key" in message)


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
    for _ in range(max_attempts):
        track_db.execute(next_id_sql)
        generated_id = track_db.fetchone()[next_id_key]
        try:
            insert_fn(generated_id)
            return generated_id
        except Exception as exc:
            last_exc = exc
            if not _is_duplicate_key_error(exc):
                raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Failed to generate an ID for insert.")
