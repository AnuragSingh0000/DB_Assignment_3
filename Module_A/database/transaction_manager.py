"""
transaction_manager.py
─────────────────────
Full ACID transaction engine layered on top of the existing B+ Tree
database. Supports BEGIN / COMMIT / ROLLBACK across multiple tables,
write-ahead logging (WAL) for durability / crash recovery, and
table-level lock management for isolation.

ACID guarantees:
  Atomicity  --> every operation in a transaction either commits or rolls back entirely.
  Consistency --> schema validation and referential constraints are checked before commit.
  Isolation  --> per-table exclusive locking serialises concurrent transactions.
  Durability --> a WAL file is fsynced before the commit record is written.
"""

import json
import os
import threading
import time
import uuid
from enum import Enum, auto
from pathlib import Path

# ──────────────────────────────────────────────
# Enumerations & Exceptions
# ──────────────────────────────────────────────

class TxStatus(Enum):
    ACTIVE    = auto()
    COMMITTED = auto()
    ABORTED   = auto()

class OpType(Enum):
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"

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
    def __init__(self, log_path: str = "wal.log"):
        self.log_path = log_path
        self._lock = threading.Lock()
        Path(log_path).touch()

    def _append(self, entry: dict):
        with self._lock:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def log_begin(self, tx_id: str):
        self._append({"type": "BEGIN", "tx_id": tx_id, "timestamp": time.time()})

    def log_operation(self, tx_id: str, op: OpType, db: str, table: str, key, before, after):
        self._append({
            "type": "OP",
            "tx_id": tx_id,
            "op": op.value,
            "db": db,
            "table": table,
            "key": key,
            "before": before,
            "after": after,
            "timestamp": time.time(),
        })

    def log_commit(self, tx_id: str):
        self._append({"type": "COMMIT", "tx_id": tx_id, "timestamp": time.time()})

    def log_abort(self, tx_id: str):
        self._append({"type": "ABORT", "tx_id": tx_id, "timestamp": time.time()})

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
        with self._lock:
            open(self.log_path, "w").close()

# ──────────────────────────────────────────────
# Lock Manager (Table-Level Locks)
# ──────────────────────────────────────────────

class LockManager:
    """
    Per-table exclusive locking.
    Locks are tracked by a string combining db + table.
    Example resource ID: 'mydb.Users'
    """
    def __init__(self):
        self._locks: dict[str, str] = {}  # resource_id → tx_id
        self._lock = threading.Lock()

    def acquire(self, tx_id: str, resource_id: str, timeout: float = 5.0):
        deadline = time.time() + timeout
        while True:
            with self._lock:
                owner = self._locks.get(resource_id)
                # Re-entrant lock: if the transaction already owns the table lock, let it proceed
                if owner is None or owner == tx_id:
                    self._locks[resource_id] = tx_id
                    return
            
            if time.time() > deadline:
                raise DeadlockError(
                    f"Transaction {tx_id} could not acquire table lock on "
                    f"'{resource_id}' (held by {self._locks.get(resource_id)})"
                )
            time.sleep(0.05)

    def release_all(self, tx_id: str):
        with self._lock:
            to_remove = [res for res, owner in self._locks.items() if owner == tx_id]
            for res in to_remove:
                del self._locks[res]

# ──────────────────────────────────────────────
# Transaction
# ──────────────────────────────────────────────

class Transaction:
    def __init__(self, tx_id: str, wal: WALManager, lock_mgr: LockManager):
        self.tx_id    = tx_id
        self.status   = TxStatus.ACTIVE
        self._wal     = wal
        self._lock_mgr = lock_mgr
        self._ops: list[dict] = []

    def _record(self, op: OpType, db_name: str, table_name: str, key, before, after):
        self._wal.log_operation(self.tx_id, op, db_name, table_name, key, before, after)
        self._ops.append({
            "op": op, "db": db_name, "table": table_name,
            "key": key, "before": before, "after": after,
        })

    def record_insert(self, db_name: str, table_name: str, key, record):
        self._record(OpType.INSERT, db_name, table_name, key, None, record)

    def record_update(self, db_name: str, table_name: str, key, old_record, new_record):
        self._record(OpType.UPDATE, db_name, table_name, key, old_record, new_record)

    def record_delete(self, db_name: str, table_name: str, key, old_record):
        self._record(OpType.DELETE, db_name, table_name, key, old_record, None)

    def lock_table(self, db_name: str, table_name: str):
        # FIX: Unique string is now just DB + Table Name
        resource_id = f"{db_name}.{table_name}"
        self._lock_mgr.acquire(self.tx_id, resource_id)

    def undo_ops(self) -> list[dict]:
        return list(reversed(self._ops))

# ──────────────────────────────────────────────
# Transaction Manager
# ──────────────────────────────────────────────

class TransactionManager:
    def __init__(self, db_manager, wal_path: str = "wal.log"):
        self._db   = db_manager
        
        # Load snapshot from disk BEFORE processing the WAL!
        if hasattr(self._db, 'load_from_disk'):
            self._db.load_from_disk('database.dat')
            
        self._wal  = WALManager(wal_path)
        self._lock_mgr = LockManager()
        self._active: dict[str, Transaction] = {}
        self._global_lock = threading.Lock()
        
        # Recover uncommitted changes
        self.recover()

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

        self._wal.log_commit(tx.tx_id)
        tx.status = TxStatus.COMMITTED
        self._lock_mgr.release_all(tx.tx_id)
        with self._global_lock:
            self._active.pop(tx.tx_id, None)
            
        if hasattr(self._db, 'save_to_disk'):
            self._db.save_to_disk('database.dat')
            
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

    def _get_table(self, db_name: str, table_name: str):
        table, msg = self._db.get_table(db_name, table_name)
        if table is None:
            raise TransactionError(f"Table not found: {db_name}.{table_name} ({msg})")
        return table

    # ── CRUD Wrappers ──

    def read(self, tx: Transaction, db_name: str, table_name: str, record_id):
        self._assert_active(tx)
        try:
            # FIX: Lock the entire table before reading
            tx.lock_table(db_name, table_name) 
            table = self._get_table(db_name, table_name)
            
            record = table.get(record_id)
            return record
        except Exception as e:
            self.rollback(tx)
            raise e

    def insert(self, tx: Transaction, db_name: str, table_name: str, key, record: dict):
        self._assert_active(tx)
        try:
            # 1. FOREIGN KEY CHECK
            table = self._get_table(db_name, table_name)
            for fk_col, target_table_name in table.foreign_keys.items():
                fk_value = record.get(fk_col)
                if fk_value is not None:
                    # FIX: Lock target table for reading during FK check
                    tx.lock_table(db_name, target_table_name)
                    target_table = self._get_table(db_name, target_table_name)
                    
                    if target_table.get(fk_value) is None:
                        raise ConstraintError(
                            f"Foreign Key Violation: '{fk_col}'={fk_value} "
                            f"does not exist in '{target_table_name}'"
                        )

            # 2. LOCK & EXECUTE
            # FIX: Lock the table being inserted into
            tx.lock_table(db_name, table_name)
            tx.record_insert(db_name, table_name, key, record)
            
            ok, msg = table.insert(record)
            if not ok:
                raise ConstraintError(f"Insert failed in '{table_name}': {msg}")

            return True, f"Inserted key={key} into {table_name}"

        except Exception as e:
            self.rollback(tx)
            raise e


    def update(self, tx: Transaction, db_name: str, table_name: str, record_id, new_record: dict):
        self._assert_active(tx)
        try:
            table = self._get_table(db_name, table_name)

            # 1. FOREIGN KEY CHECK
            for fk_col, target_table_name in table.foreign_keys.items():
                fk_value = new_record.get(fk_col)
                if fk_value is not None:
                    # FIX: Lock target table
                    tx.lock_table(db_name, target_table_name)
                    target_table = self._get_table(db_name, target_table_name)
                    
                    if target_table.get(fk_value) is None:
                        raise ConstraintError(
                            f"Foreign Key Violation: '{fk_col}'={fk_value} "
                            f"does not exist in '{target_table_name}'"
                        )

            # 2. LOCK & FETCH OLD
            # FIX: Lock main table
            tx.lock_table(db_name, table_name)
            old = table.get(record_id)
            if old is None:
                raise TransactionError(f"Update failed: Record {record_id} not found")

            # 3. REVERSE FOREIGN KEY CHECK (Ghost Rule for PK updates)
            if old[table.search_key] != new_record[table.search_key]:
                for child_table_name, child_col in table.referenced_by:
                    # FIX: Lock child table
                    tx.lock_table(db_name, child_table_name)
                    child_table = self._get_table(db_name, child_table_name)
                    for _, child_rec in child_table.get_all():
                        if child_rec.get(child_col) == record_id:
                            raise ConstraintError(
                                f"Foreign Key Violation: Cannot change PK '{record_id}' in '{table_name}'. "
                                f"It is still referenced by '{child_table_name}'."
                            )

            # 4. WAL & EXECUTE
            tx.record_update(db_name, table_name, record_id, old, new_record)
            
            ok, msg = table.update(record_id, new_record)
            if not ok:
                raise ConstraintError(f"Update failed in '{table_name}': {msg}")

            return True, f"Updated key={record_id}"

        except Exception as e:
            self.rollback(tx)
            raise e


    def delete(self, tx: Transaction, db_name: str, table_name: str, record_id):
        self._assert_active(tx)
        try:
            table = self._get_table(db_name, table_name)

            # FIX: Lock the Parent (main) table FIRST to prevent deadlocks
            tx.lock_table(db_name, table_name)
            old = table.get(record_id)
            if old is None:
                raise TransactionError(f"Delete failed: Record {record_id} not found")

            # REVERSE FOREIGN KEY CHECK (Ghost Rule)
            for child_table_name, child_col in table.referenced_by:
                # FIX: Lock the Child tables SECOND
                tx.lock_table(db_name, child_table_name)
                child_table = self._get_table(db_name, child_table_name)
                
                for _, child_rec in child_table.get_all():
                    if child_rec.get(child_col) == record_id:
                        raise ConstraintError(
                            f"Foreign Key Violation: Cannot delete '{record_id}' from '{table_name}'. "
                            f"It is still referenced by '{child_table_name}'."
                        )

            tx.record_delete(db_name, table_name, record_id, old)
            
            ok, msg = table.delete(record_id)
            if not ok:
                raise ConstraintError(f"Delete failed in '{table_name}': {msg}")

            return True, f"Deleted key={record_id}"

        except Exception as e:
            self.rollback(tx)
            raise e
        

    def _assert_active(self, tx: Transaction):
        if tx.status != TxStatus.ACTIVE:
            raise TransactionError(f"Transaction {tx.tx_id} is {tx.status.name}, not ACTIVE")

    def _undo_single(self, op_entry: dict):
        op    = op_entry["op"]
        db    = op_entry["db"]
        tname = op_entry["table"]
        key   = op_entry["key"]

        table = self._get_table(db, tname)

        if op == OpType.INSERT:
            table.delete(key)
        elif op == OpType.DELETE:
            table.insert(op_entry["before"])
        elif op == OpType.UPDATE:
            old_record = op_entry["before"]
            new_record = op_entry.get("after") 
            
            old_pk = old_record[table.search_key]
            
            if new_record and new_record[table.search_key] != old_pk:
                new_pk = new_record[table.search_key]
                table.delete(new_pk)
                table.insert(old_record)
            else:
                table.update(old_pk, old_record)

    def _redo_single(self, op_entry: dict):
        """Idempotent REDO operation for committed transactions."""
        op    = OpType(op_entry["op"])
        db    = op_entry["db"]
        tname = op_entry["table"]
        key   = op_entry["key"]

        table = self._get_table(db, tname)

        if op == OpType.INSERT:
            if table.get(key) is None:  # Idempotency check
                table.insert(op_entry["after"])
        elif op == OpType.DELETE:
            if table.get(key) is not None:
                table.delete(key)
        elif op == OpType.UPDATE:
            old_pk = op_entry["before"][table.search_key]
            new_record = op_entry["after"]
            new_pk = new_record[table.search_key]
            
            # If the PK changed during the update
            if old_pk != new_pk:
                if table.get(old_pk) is not None:
                    table.delete(old_pk)
                if table.get(new_pk) is None:
                    table.insert(new_record)
            else:
                # Normal update
                if table.get(old_pk) is not None:
                    table.update(old_pk, new_record)

    def recover(self):
        entries = self._wal.read_log()
        if not entries:
            return

        tx_logs: dict[str, list] = {}
        tx_final: dict[str, str] = {}

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

        # ─── PHASE 1: REDO COMMITTED TRANSACTIONS ───
        # Apply ops forwards (chronological order)
        redo_count = 0
        for tid, ops in tx_logs.items():
            if tx_final.get(tid) == "COMMIT":
                for op_entry in ops:
                    try:
                        self._redo_single(op_entry)
                    except Exception as ex:
                        print(f"  [Recovery] REDO warning on tx={tid}: {ex}")
                redo_count += 1
                
        if redo_count:
            print(f"[Recovery] REDONE {redo_count} committed transaction(s)")

        # ─── PHASE 2: UNDO INCOMPLETE TRANSACTIONS ───
        # Apply ops backwards (reverse chronological order)
        rolled_back = []
        for tid, ops in tx_logs.items():
            final = tx_final.get(tid)
            if final == "COMMIT":
                continue 
            
            if final is None:
                print(f"[Recovery] UNDOING incomplete tx={tid} ({len(ops)} ops)")
                for op_entry in reversed(ops):
                    try:
                        self._undo_single({
                            "op":     OpType(op_entry["op"]),
                            "db":     op_entry["db"],
                            "table":  op_entry["table"],
                            "key":    op_entry["key"],
                            "before": op_entry.get("before"),
                            "after":  op_entry.get("after"),
                        })
                    except Exception as ex:
                        print(f"  [Recovery] UNDO warning: {ex}")
                rolled_back.append(tid)

        if rolled_back:
            print(f"[Recovery] UNDONE {len(rolled_back)} incomplete transaction(s)")

        # Save the fully recovered state to disk and clear the WAL
        if hasattr(self._db, 'save_to_disk'):
            self._db.save_to_disk('database.dat')
        self._wal.clear()
        print("[Recovery] WAL compacted")