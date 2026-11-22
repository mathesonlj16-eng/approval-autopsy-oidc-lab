"""Disposable SQLite ApprovalStore for cross-process contract research.

Research-only adapter, NOT supplied by Microsoft or security-hardened production
code. Explicit JSON encoding; no untrusted pickle or external credentials.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from agentmesh.governance.approval_protocol import (
    ApprovalChainEntry,
    ApprovalRequest,
    ApprovalResolution,
    ApprovalStatus,
    ApproverKind,
    EntryDecision,
    Outcome,
)


def encode(record):
    return json.dumps(asdict(record), default=lambda value: value.isoformat()
                      if isinstance(value, datetime) else str(value), sort_keys=True)


def decode_request(encoded):
    value = json.loads(encoded)
    value["expires_at"] = datetime.fromisoformat(value["expires_at"])
    value["requested_at"] = datetime.fromisoformat(value["requested_at"])
    value["status"] = ApprovalStatus(value["status"])
    return ApprovalRequest(**value)


def decode_entry(encoded):
    value = json.loads(encoded)
    value["decided_at"] = datetime.fromisoformat(value["decided_at"])
    value["approver_kind"] = ApproverKind(value["approver_kind"])
    value["decision"] = EntryDecision(value["decision"])
    return ApprovalChainEntry(**value)


def decode_resolution(encoded):
    value = json.loads(encoded)
    value["resolved_at"] = datetime.fromisoformat(value["resolved_at"])
    value["outcome"] = Outcome(value["outcome"])
    return ApprovalResolution(**value)


class SQLiteApprovalStore:
    """Cross-process SQLite reference store with transaction-capable extension.

    Original upstream ApprovalCoordinator ignores approval_transaction;
    candidate patch acquires BEGIN IMMEDIATE and keeps all protocol methods
    on the same connection through submit_entry. Both use identical storage.
    """

    def __init__(self, db_path, vote_gate=None):
        self.db_path = str(Path(db_path).resolve())
        self._local = threading.local()
        self._vote_gate = vote_gate
        self._gate_used = False
        with self._connection(write=True) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS entries ("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                "id TEXT UNIQUE NOT NULL, req_id TEXT NOT NULL, value TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS resolutions ("
                "req_id TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def _open(self):
        db = sqlite3.connect(self.db_path, isolation_level=None, timeout=12)
        db.execute("PRAGMA busy_timeout=12000")
        return db

    @contextmanager
    def _connection(self, *, write=False):
        existing = getattr(self._local, "transaction", None)
        if existing is not None:
            yield existing
            return
        db = self._open()
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def approval_transaction(self, approval_request_id):
        """Atomic submission for the candidate patched coordinator.

        A real external backend would need its equivalent DB transaction and
        concurrency design, not a process-local threading lock.
        """
        if getattr(self._local, "transaction", None) is not None:
            raise RuntimeError("Nested approval transactions are not supported")
        db = self._open()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._local.transaction = db
            yield
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            self._local.transaction = None
            db.close()

    def save_request(self, request):
        with self._connection(write=True) as db:
            db.execute(
                "INSERT INTO requests (id, value) VALUES (?, ?)",
                (request.approval_request_id, encode(request)),
            )

    def get_request(self, approval_request_id):
        with self._connection() as db:
            row = db.execute(
                "SELECT value FROM requests WHERE id = ?", (approval_request_id,)
            ).fetchone()
        return decode_request(row[0]) if row else None

    def set_status(self, approval_request_id, status):
        with self._connection(write=True) as db:
            row = db.execute(
                "SELECT value FROM requests WHERE id = ?", (approval_request_id,)
            ).fetchone()
            if row:
                request = decode_request(row[0])
                request.status = status
                db.execute(
                    "UPDATE requests SET value = ? WHERE id = ?",
                    (encode(request), approval_request_id),
                )

    def append_entry(self, entry):
        with self._connection(write=True) as db:
            db.execute(
                "INSERT INTO entries (id, req_id, value) VALUES (?, ?, ?)",
                (entry.chain_entry_id, entry.approval_request_id, encode(entry)),
            )

    def get_entries(self, approval_request_id):
        with self._connection() as db:
            rows = db.execute(
                "SELECT value FROM entries WHERE req_id = ? ORDER BY seq",
                (approval_request_id,),
            ).fetchall()
        entries = [decode_entry(row[0]) for row in rows]
        if self._vote_gate is not None and not self._gate_used:
            self._gate_used = True
            try:
                self._vote_gate.wait(timeout=1.5)
            except threading.BrokenBarrierError:
                # The patched transaction blocks the other process from
                # reaching this read until the current vote completes.
                pass
        return entries

    def save_resolution(self, resolution):
        with self._connection(write=True) as db:
            db.execute(
                "INSERT OR IGNORE INTO resolutions (req_id, value) VALUES (?, ?)",
                (resolution.approval_request_id, encode(resolution)),
            )

    def get_resolution(self, approval_request_id):
        with self._connection() as db:
            row = db.execute(
                "SELECT value FROM resolutions WHERE req_id = ?",
                (approval_request_id,),
            ).fetchone()
        return decode_resolution(row[0]) if row else None

    def consume(self, approval_request_id):
        with self._connection(write=True) as db:
            row = db.execute(
                "SELECT value FROM requests WHERE id = ?",
                (approval_request_id,),
            ).fetchone()
            if not row:
                return False
            request = decode_request(row[0])
            if request.status != ApprovalStatus.ALLOWED:
                return False
            request.status = ApprovalStatus.CONSUMED
            db.execute(
                "UPDATE requests SET value = ? WHERE id = ?",
                (encode(request), approval_request_id),
            )
            return True
