import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone

_audit_lock = threading.Lock()

_log_path = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "audit.log")

_log_path = os.path.abspath(_log_path)

_file_logger = logging.getLogger("audit")

_file_logger.setLevel(logging.INFO)

if not _file_logger.handlers:
    os.makedirs(os.path.dirname(_log_path), exist_ok=True)
    _handler = logging.FileHandler(_log_path, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _file_logger.addHandler(_handler)


def _compute_entry_hash(
    timestamp, user_id, username, action,
    table_name, record_id, status, details, ip_address, prev_hash,
) -> str:
    canonical = "|".join([
        str(timestamp),
        str(user_id or ""),
        str(username or ""),
        str(action),
        str(table_name or ""),
        str(record_id or ""),
        str(status),
        str(details or ""),
        str(ip_address or ""),
        str(prev_hash),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_audit_log(
    db,
    user_id,
    username: str,
    action: str,
    table_name: str,
    record_id,
    status: str,
    details,
    ip_address: str,
) -> None:
    with _audit_lock:
        db.execute("SELECT entry_hash FROM audit_log ORDER BY log_id DESC LIMIT 1")
        last = db.fetchone()
        prev_hash = last["entry_hash"] if last else "0" * 64
        _now = datetime.now(timezone.utc)
        _ms  = _now.microsecond // 1000
        ts   = _now.strftime("%Y-%m-%d %H:%M:%S") + f".{_ms:03d}"
        details_str = json.dumps(details) if details is not None else None
        entry_hash = _compute_entry_hash(
            ts, user_id, username, action,
            table_name, record_id, status, details_str, ip_address, prev_hash,
        )
        db.execute(
            """
            INSERT INTO audit_log
                (timestamp, user_id, username, action, table_name, record_id,
                 status, details, ip_address, prev_hash, entry_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                ts, user_id, username, action, table_name, record_id,
                status, details_str, ip_address, prev_hash, entry_hash,
            ),
        )
        _file_logger.info(
            f"{ts} | {username} | {action} | {table_name} | {status} | hash={entry_hash}"
        )


def verify_audit_chain(db) -> dict:
    db.execute("SELECT * FROM audit_log ORDER BY log_id ASC")
    entries = db.fetchall()
    prev_hash = "0" * 64
    for entry in entries:
        ts_val = entry["timestamp"]
        if hasattr(ts_val, "strftime"):
            _ms  = ts_val.microsecond // 1000
            ts_str = ts_val.strftime("%Y-%m-%d %H:%M:%S") + f".{_ms:03d}"
        else:
            ts_str = str(ts_val)
        if entry.get("prev_hash", prev_hash) != prev_hash:
            return {"intact": False, "tampered_at_log_id": entry["log_id"]}
        expected = _compute_entry_hash(
            ts_str, entry["user_id"], entry["username"],
            entry["action"], entry["table_name"], entry["record_id"],
            entry["status"], entry["details"], entry["ip_address"],
            prev_hash,
        )
        if expected != entry["entry_hash"]:
            return {"intact": False, "tampered_at_log_id": entry["log_id"]}
        prev_hash = entry["entry_hash"]
    return {"intact": True, "total_entries": len(entries)}
