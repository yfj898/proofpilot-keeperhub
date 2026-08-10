from __future__ import annotations

import hashlib
import os
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


UNRESOLVED_STATES = frozenset({"PREPARED", "SUBMITTED", "CONFIRMED"})


class ReconciliationRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    semantic_key: str
    intent_commitment: str
    payload_sha256: str
    idempotency_key: str
    state: str
    execution_id: str | None
    transaction_hash: str | None
    created_at: str
    updated_at: str


def operation_semantic_key(*, account: str, user_intent: str) -> str:
    """Return a stable identity for one user-authorized semantic operation.

    Execution payloads are deliberately excluded. They are separate commitments that
    the journal compares when recovering an unresolved operation.
    """
    normalized_intent = " ".join(unicodedata.normalize("NFKC", user_intent).split())
    body = "\n".join((account.lower(), normalized_intent)).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


class OperationJournal:
    """Crash-safe local journal for KeeperHub direct writes.

    PREPARED is committed before the first broadcast attempt, so a restart reuses the
    same KeeperHub idempotency key instead of minting a second write. A PREPARED record
    older than KeeperHub's replay window is never auto-rebroadcast.
    """

    def __init__(self, path: Path, *, replay_window_hours: int = 24):
        self.path = path
        self.replay_window = timedelta(hours=replay_window_hours)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.name == ".proofpilot":
            path.parent.chmod(0o700)
        if not path.exists():
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(descriptor)
        path.chmod(0o600)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    semantic_key TEXT NOT NULL,
                    intent_commitment TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    execution_id TEXT,
                    transaction_hash TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_operations_semantic_state "
                "ON operations(semantic_key, state, created_at)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_one_unresolved_semantic "
                "ON operations(semantic_key) "
                "WHERE state IN ('PREPARED', 'SUBMITTED', 'CONFIRMED')"
            )

    def prepare(
        self,
        *,
        semantic_key: str,
        intent_commitment: str,
        payload_sha256: str,
    ) -> OperationRecord:
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            # Serialize the unresolved lookup and insert across processes. The partial
            # unique index remains the database-level backstop.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM operations
                WHERE semantic_key = ? AND state IN ('PREPARED', 'SUBMITTED', 'CONFIRMED')
                ORDER BY created_at DESC LIMIT 1
                """,
                (semantic_key,),
            ).fetchone()
            if row is not None:
                record = self._record(row)
                if record.payload_sha256 != payload_sha256:
                    raise ReconciliationRequired(
                        "An unresolved operation exists for the same semantic action with "
                        "a different canonical execution payload."
                    )
                # A restarted compiler may mint a fresh nonce and therefore a new intent
                # commitment. The durable PREPARED record is the authorization commitment
                # that crossed the write boundary; recovery must reuse it rather than mint
                # a second KeeperHub write.
                created = datetime.fromisoformat(record.created_at)
                if record.state == "PREPARED" and now - created >= self.replay_window:
                    raise ReconciliationRequired(
                        "A PREPARED write is older than KeeperHub's idempotency replay window; "
                        "manual reconciliation is required before any new broadcast."
                    )
                return record

            stamp = now.isoformat()
            operation_id = f"op_{uuid.uuid4().hex}"
            idempotency_key = f"proofpilot-op-{uuid.uuid4()}"
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, semantic_key, intent_commitment, payload_sha256,
                    idempotency_key, state, execution_id, transaction_hash,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'PREPARED', NULL, NULL, ?, ?)
                """,
                (
                    operation_id,
                    semantic_key,
                    intent_commitment,
                    payload_sha256,
                    idempotency_key,
                    stamp,
                    stamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            assert row is not None
            return self._record(row)

    def mark_submitted(self, operation_id: str, execution_id: str) -> OperationRecord:
        return self._transition(operation_id, "SUBMITTED", execution_id=execution_id)

    def mark_confirmed(self, operation_id: str, transaction_hash: str) -> OperationRecord:
        return self._transition(operation_id, "CONFIRMED", transaction_hash=transaction_hash)

    def mark_verified(self, operation_id: str) -> OperationRecord:
        return self._transition(operation_id, "VERIFIED")

    def mark_failed(self, operation_id: str) -> OperationRecord:
        return self._transition(operation_id, "FAILED")

    def get(self, operation_id: str) -> OperationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            return self._record(row) if row is not None else None

    def _transition(
        self,
        operation_id: str,
        state: str,
        *,
        execution_id: str | None = None,
        transaction_hash: str | None = None,
    ) -> OperationRecord:
        stamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if current is None:
                raise KeyError(operation_id)
            connection.execute(
                """
                UPDATE operations
                SET state = ?,
                    execution_id = COALESCE(?, execution_id),
                    transaction_hash = COALESCE(?, transaction_hash),
                    updated_at = ?
                WHERE operation_id = ?
                """,
                (state, execution_id, transaction_hash, stamp, operation_id),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            assert row is not None
            return self._record(row)

    @staticmethod
    def _record(row: sqlite3.Row) -> OperationRecord:
        return OperationRecord(
            operation_id=str(row["operation_id"]),
            semantic_key=str(row["semantic_key"]),
            intent_commitment=str(row["intent_commitment"]),
            payload_sha256=str(row["payload_sha256"]),
            idempotency_key=str(row["idempotency_key"]),
            state=str(row["state"]),
            execution_id=row["execution_id"],
            transaction_hash=row["transaction_hash"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
