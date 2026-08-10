from __future__ import annotations

import sys
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.operation_journal import (  # noqa: E402
    OperationJournal,
    ReconciliationRequired,
    operation_semantic_key,
)


class OperationJournalTests(unittest.TestCase):
    def test_journal_creates_private_directory_and_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / ".proofpilot"
            path = directory / "operations.sqlite3"

            OperationJournal(path)

            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_semantic_key_is_stable_across_execution_payloads(self) -> None:
        account = "0x" + "A" * 40
        user_intent = "  Set Aave   E-Mode to 1  "

        key_for_payload_a = operation_semantic_key(
            account=account,
            user_intent=user_intent,
        )
        key_for_payload_b = operation_semantic_key(
            account=account,
            user_intent=user_intent,
        )

        self.assertEqual(key_for_payload_a, key_for_payload_b)
        self.assertEqual(
            key_for_payload_a,
            operation_semantic_key(
                account=account.lower(),
                user_intent="Set Aave E-Mode to 1",
            ),
        )

    def test_unresolved_operation_reuses_same_idempotency_key_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ops.sqlite3"
            semantic_key = operation_semantic_key(
                account="0x" + "1" * 40,
                user_intent="Set Aave E-Mode to 1",
            )
            first = OperationJournal(path).prepare(
                semantic_key=semantic_key,
                intent_commitment="b" * 64,
                payload_sha256="a" * 64,
            )
            OperationJournal(path).mark_submitted(first.operation_id, "exec-1")
            recovered = OperationJournal(path).prepare(
                semantic_key=semantic_key,
                intent_commitment="c" * 64,
                payload_sha256="a" * 64,
            )
            self.assertEqual(recovered.operation_id, first.operation_id)
            self.assertEqual(recovered.idempotency_key, first.idempotency_key)
            self.assertEqual(recovered.execution_id, "exec-1")
            self.assertEqual(recovered.state, "SUBMITTED")
            self.assertEqual(recovered.intent_commitment, "b" * 64)

    def test_unresolved_operation_with_changed_payload_requires_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ops.sqlite3"
            semantic_key = operation_semantic_key(
                account="0x" + "1" * 40,
                user_intent="Set Aave E-Mode to 1",
            )
            first = OperationJournal(path).prepare(
                semantic_key=semantic_key,
                intent_commitment="b" * 64,
                payload_sha256="a" * 64,
            )

            with self.assertRaises(ReconciliationRequired):
                OperationJournal(path).prepare(
                    semantic_key=semantic_key,
                    intent_commitment="c" * 64,
                    payload_sha256="d" * 64,
                )

            with sqlite3.connect(path) as connection:
                count, distinct_keys = connection.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT idempotency_key) FROM operations"
                ).fetchone()
            recovered = OperationJournal(path).prepare(
                semantic_key=semantic_key,
                intent_commitment="c" * 64,
                payload_sha256="a" * 64,
            )
            self.assertEqual((count, distinct_keys), (1, 1))
            self.assertEqual(recovered.operation_id, first.operation_id)
            self.assertEqual(recovered.idempotency_key, first.idempotency_key)

    def test_prepared_operation_reuses_same_idempotency_key_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ops.sqlite3"
            first = OperationJournal(path).prepare(
                semantic_key="semantic",
                intent_commitment="b" * 64,
                payload_sha256="a" * 64,
            )
            recovered = OperationJournal(path).prepare(
                semantic_key="semantic",
                intent_commitment="c" * 64,
                payload_sha256="a" * 64,
            )
            self.assertEqual(recovered.operation_id, first.operation_id)
            self.assertEqual(recovered.idempotency_key, first.idempotency_key)
            self.assertEqual(recovered.state, "PREPARED")

    def test_prepared_operation_outside_replay_window_requires_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ops.sqlite3"
            journal = OperationJournal(path, replay_window_hours=0)
            journal.prepare(
                semantic_key="semantic",
                intent_commitment="b" * 64,
                payload_sha256="a" * 64,
            )
            with self.assertRaises(ReconciliationRequired):
                journal.prepare(
                    semantic_key="semantic",
                    intent_commitment="b" * 64,
                    payload_sha256="a" * 64,
                )

    def test_verified_operation_allows_new_intentional_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ops.sqlite3"
            journal = OperationJournal(path)
            first = journal.prepare(
                semantic_key="semantic",
                intent_commitment="b" * 64,
                payload_sha256="a" * 64,
            )
            journal.mark_verified(first.operation_id)
            second = journal.prepare(
                semantic_key="semantic",
                intent_commitment="b" * 64,
                payload_sha256="a" * 64,
            )
            self.assertNotEqual(second.operation_id, first.operation_id)


if __name__ == "__main__":
    unittest.main()
