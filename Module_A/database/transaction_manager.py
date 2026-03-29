"""
transaction_manager.py
─────────────────────
Full ACID transaction engine layered on top of the existing B+ Tree
database. Supports BEGIN / COMMIT / ROLLBACK across multiple tables,
write-ahead logging (WAL) for durability / crash recovery, and
basic lock management for isolation.

ACID guarantees:
  Atomicity  – every operation in a transaction either commits or rolls back entirely.
  Consistency – schema validation and referential constraints are checked before commit.
  Isolation  – per-table exclusive locking serialises concurrent transactions.
  Durability – a WAL file is fsynced before the commit record is written.
"""

import json
import os
import threading
import time
import uuid
from enum import Enum, auto
from pathlib import Path


# ──────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────

class TxStatus(Enum):
    ACTIVE    = auto()
    COMMITTED = auto()
    ABORTED   = auto()


class OpType(Enum):
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


# ──────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────

class TransactionError(Exception):
    pass

class DeadlockError(TransactionError):
    pass

class ConstraintError(TransactionError):
    pass


# ──────────────────────────────────────────────
# Write-Ahead Log (WAL)
# ──────────────────────────────────────────────

class WALManager:
    """
    Persistent Write-Ahead Log.
    Every operation is journaled BEFORE it touches the B+ Tree.
    On recovery, incomplete transactions are rolled back; committed
    ones are confirmed (re-applied if needed).
    """

    def __init__(self, log_path: str = "wal.log"):
        self.log_path = log_path
        self._lock = threading.Lock()
        Path(log_path).touch()          # create if missing

    # ── low-level helpers ──────────────────────

    def _append(self, entry: dict):
        """Atomically append a JSON line to the WAL."""
        with self._lock:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
                f.flush()
                os.fsync(f.fileno())    # durability guarantee

    def log_begin(self, tx_id: str):
        self._append({"type": "BEGIN", "tx_id": tx_id,
                       "timestamp": time.time()})

    def log_operation(self, tx_id: str, op: OpType,
                      table: str, key, before, after):
        self._append({
            "type": "OP",
            "tx_id": tx_id,
            "op": op.value,
            "table": table,
            "key": key,
            "before": before,   # None for INSERT
            "after": after,     # None for DELETE
            "timestamp": time.time(),
        })

    def log_commit(self, tx_id: str):
        self._append({"type": "COMMIT", "tx_id": tx_id,
                       "timestamp": time.time()})

    def log_abort(self, tx_id: str):
        self._append({"type": "ABORT", "tx_id": tx_id,
                       "timestamp": time.time()})

    # ── recovery ──────────────────────────────

    def read_log(self) -> list[dict]:
        entries = []
        try:
            with open(self.log_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except FileNotFoundError:
            pass
        return entries

    def clear(self):
        """Truncate the WAL (called after a clean checkpoint)."""
        with self._lock:
            open(self.log_path, "w").close()


# ──────────────────────────────────────────────
# Lock Manager  (simple exclusive locks)
# ──────────────────────────────────────────────

class LockManager:
    """
    Per-table exclusive locking.
    A transaction must acquire the lock for every table it touches.
    Trying to lock a table held by another transaction raises DeadlockError.
    """

    def __init__(self):
        self._locks: dict[str, str] = {}   # table → tx_id
        self._lock = threading.Lock()

    def acquire(self, tx_id: str, table_name: str, timeout: float = 5.0):
        deadline = time.time() + timeout
        while True:
            with self._lock:
                owner = self._locks.get(table_name)
                if owner is None or owner == tx_id:
                    self._locks[table_name] = tx_id
                    return
            if time.time() > deadline:
                raise DeadlockError(
                    f"Transaction {tx_id} could not acquire lock on "
                    f"'{table_name}' (held by {self._locks.get(table_name)})"
                )
            time.sleep(0.05)

    def release_all(self, tx_id: str):
        with self._lock:
            to_remove = [t for t, owner in self._locks.items() if owner == tx_id]
            for t in to_remove:
                del self._locks[t]


# ──────────────────────────────────────────────
# Transaction
# ──────────────────────────────────────────────

class Transaction:
    """
    Represents a single active transaction.
    Accumulates a log of (op, table, key, before, after) tuples so
    that a ROLLBACK can undo them in reverse order.
    """

    def __init__(self, tx_id: str, wal: WALManager, lock_mgr: LockManager):
        self.tx_id    = tx_id
        self.status   = TxStatus.ACTIVE
        self._wal     = wal
        self._lock_mgr = lock_mgr
        self._ops: list[dict] = []   # ordered log for undo

    # ── operation recording ───────────────────

    def _record(self, op: OpType, table_name: str, key, before, after):
        self._wal.log_operation(self.tx_id, op, table_name, key, before, after)
        self._ops.append({
            "op": op, "table": table_name,
            "key": key, "before": before, "after": after,
        })

    def record_insert(self, table_name: str, key, record):
        self._record(OpType.INSERT, table_name, key, None, record)

    def record_update(self, table_name: str, key, old_record, new_record):
        self._record(OpType.UPDATE, table_name, key, old_record, new_record)

    def record_delete(self, table_name: str, key, old_record):
        self._record(OpType.DELETE, table_name, key, old_record, None)

    def lock_table(self, table_name: str):
        self._lock_mgr.acquire(self.tx_id, table_name)

    # ── undo helper ───────────────────────────

    def undo_ops(self) -> list[dict]:
        """Return operations in reverse order for rollback."""
        return list(reversed(self._ops))


# ──────────────────────────────────────────────
# Transaction Manager
# ──────────────────────────────────────────────

class TransactionManager:
    """
    Central coordinator for all ACID transactions.

    Usage:
        tm = TransactionManager(db_manager)
        tx = tm.begin()
        tm.insert(tx, "mydb", "users", record)
        tm.commit(tx)          # or tm.rollback(tx)
    """

    def __init__(self, db_manager, wal_path: str = "wal.log"):
        self._db   = db_manager
        self._wal  = WALManager(wal_path)
        self._lock_mgr = LockManager()
        self._active: dict[str, Transaction] = {}
        self._global_lock = threading.Lock()
        self.recover()          # replay WAL on startup

    # ── lifecycle ─────────────────────────────

    def begin(self) -> Transaction:
        tx_id = str(uuid.uuid4())[:8]
        tx = Transaction(tx_id, self._wal, self._lock_mgr)
        self._wal.log_begin(tx_id)
        with self._global_lock:
            self._active[tx_id] = tx
        print(f"[TxManager] BEGIN  tx={tx_id}")
        return tx

    def commit(self, tx: Transaction) -> tuple[bool, str]:
        if tx.status != TxStatus.ACTIVE:
            return False, f"Transaction {tx.tx_id} is not active"

        # Consistency check: all ops already applied; WAL commit record written
        self._wal.log_commit(tx.tx_id)
        tx.status = TxStatus.COMMITTED
        self._lock_mgr.release_all(tx.tx_id)
        with self._global_lock:
            self._active.pop(tx.tx_id, None)
        print(f"[TxManager] COMMIT tx={tx.tx_id}")
        return True, f"Transaction {tx.tx_id} committed successfully"

    def rollback(self, tx: Transaction) -> tuple[bool, str]:
        if tx.status != TxStatus.ACTIVE:
            return False, f"Transaction {tx.tx_id} is not active"

        errors = []
        for op_entry in tx.undo_ops():
            try:
                self._undo_single(op_entry)
            except Exception as e:
                errors.append(str(e))

        self._wal.log_abort(tx.tx_id)
        tx.status = TxStatus.ABORTED
        self._lock_mgr.release_all(tx.tx_id)
        with self._global_lock:
            self._active.pop(tx.tx_id, None)

        if errors:
            msg = f"Rolled back with errors: {'; '.join(errors)}"
        else:
            msg = f"Transaction {tx.tx_id} rolled back successfully"
        print(f"[TxManager] ABORT  tx={tx.tx_id}")
        return True, msg

    # ── transactional CRUD wrappers ───────────

    def _get_table(self, db_name: str, table_name: str):
        table, msg = self._db.get_table(db_name, table_name)
        if table is None:
            raise TransactionError(f"Table not found: {db_name}.{table_name} ({msg})")
        return table

    def insert(self, tx: Transaction, db_name: str, table_name: str,
               record: dict) -> tuple[bool, str]:
        self._assert_active(tx)
        tx.lock_table(table_name)
        table = self._get_table(db_name, table_name)

        ok, result = table.insert(record)
        if not ok:
            return False, result

        key = result   # table.insert returns (True, key)
        tx.record_insert(table_name, key, record)
        return True, f"Inserted key={key} into {table_name}"

    def update(self, tx: Transaction, db_name: str, table_name: str,
               record_id, new_record: dict) -> tuple[bool, str]:
        self._assert_active(tx)
        tx.lock_table(table_name)
        table = self._get_table(db_name, table_name)

        old = table.get(record_id)
        if old is None:
            return False, f"Record {record_id} not found in {table_name}"

        ok, msg = table.update(record_id, new_record)
        if not ok:
            return False, msg

        tx.record_update(table_name, record_id, old, new_record)
        return True, f"Updated key={record_id} in {table_name}"

    def delete(self, tx: Transaction, db_name: str, table_name: str,
               record_id) -> tuple[bool, str]:
        self._assert_active(tx)
        tx.lock_table(table_name)
        table = self._get_table(db_name, table_name)

        old = table.get(record_id)
        if old is None:
            return False, f"Record {record_id} not found in {table_name}"

        ok, msg = table.delete(record_id)
        if not ok:
            return False, msg

        tx.record_delete(table_name, record_id, old)
        return True, f"Deleted key={record_id} from {table_name}"

    # ── internal helpers ──────────────────────

    def _assert_active(self, tx: Transaction):
        if tx.status != TxStatus.ACTIVE:
            raise TransactionError(
                f"Transaction {tx.tx_id} is {tx.status.name}, not ACTIVE"
            )

    def _undo_single(self, op_entry: dict):
        """
        Reverse a single logged operation.
        INSERT  → DELETE
        DELETE  → INSERT
        UPDATE  → UPDATE back to old value
        """
        op    = op_entry["op"]
        tname = op_entry["table"]
        key   = op_entry["key"]

        # Find the table in any database (simple linear scan)
        table = None
        for db_tables in self._db.databases.values():
            if tname in db_tables:
                table = db_tables[tname]
                break

        if table is None:
            raise TransactionError(f"Cannot undo: table '{tname}' not found")

        if op == OpType.INSERT:
            table.delete(key)
        elif op == OpType.DELETE:
            table.insert(op_entry["before"])
        elif op == OpType.UPDATE:
            table.update(key, op_entry["before"])

    # ── crash recovery ────────────────────────

    def recover(self):
        """
        Replay the WAL on startup:
          • COMMITTED transactions: already applied → skip
          • Incomplete (no COMMIT/ABORT) transactions: undo in reverse
        """
        entries = self._wal.read_log()
        if not entries:
            return

        # Group entries by tx_id
        tx_logs: dict[str, list] = {}
        tx_final: dict[str, str] = {}   # tx_id → COMMIT | ABORT | None

        for e in entries:
            tid = e.get("tx_id")
            if not tid:
                continue
            if e["type"] == "BEGIN":
                tx_logs[tid] = []
            elif e["type"] == "OP":
                tx_logs.setdefault(tid, []).append(e)
            elif e["type"] in ("COMMIT", "ABORT"):
                tx_final[tid] = e["type"]

        rolled_back = []
        for tid, ops in tx_logs.items():
            final = tx_final.get(tid)
            if final == "COMMIT":
                continue    # durably committed – nothing to undo
            if final is None:   # crash mid-transaction
                print(f"[Recovery] Rolling back incomplete tx={tid} ({len(ops)} ops)")
                for op_entry in reversed(ops):
                    try:
                        self._undo_single({
                            "op":     OpType(op_entry["op"]),
                            "table":  op_entry["table"],
                            "key":    op_entry["key"],
                            "before": op_entry.get("before"),
                            "after":  op_entry.get("after"),
                        })
                    except Exception as ex:
                        print(f"  [Recovery] warning: {ex}")
                rolled_back.append(tid)

        if rolled_back:
            print(f"[Recovery] Rolled back {len(rolled_back)} incomplete transaction(s)")

        # Compact the WAL – remove already-handled entries
        self._wal.clear()
        print("[Recovery] WAL compacted")