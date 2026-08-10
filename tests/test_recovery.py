from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.models import RecoveryAction  # noqa: E402
from proofpilot.recovery import (  # noqa: E402
    FailureKind,
    RecoveryContext,
    RecoveryPolicy,
    classify_failure,
)


class RecoveryTests(unittest.TestCase):
    def test_insufficient_balance_stops(self) -> None:
        decision = RecoveryPolicy().decide(RecoveryContext(FailureKind.INSUFFICIENT_BALANCE))
        self.assertEqual(decision.action, RecoveryAction.STOP)
        self.assertFalse(decision.safe_to_repeat_write)

    def test_pending_timeout_queries_status_not_rebroadcast(self) -> None:
        decision = RecoveryPolicy().decide(
            RecoveryContext(FailureKind.EXECUTION_PENDING_TIMEOUT)
        )
        self.assertEqual(decision.action, RecoveryAction.RETRY_STATUS)
        self.assertFalse(decision.safe_to_repeat_write)

    def test_stale_state_resimulates(self) -> None:
        decision = RecoveryPolicy().decide(RecoveryContext(FailureKind.STALE_STATE))
        self.assertEqual(decision.action, RecoveryAction.RESIMULATE)
        self.assertFalse(decision.safe_to_repeat_write)

    def test_budget_exhaustion_fails_closed(self) -> None:
        decision = RecoveryPolicy().decide(
            RecoveryContext(FailureKind.TRANSIENT_NETWORK, attempt=2, max_attempts=2)
        )
        self.assertEqual(decision.action, RecoveryAction.STOP)

    def test_classifies_live_gate0_balance_error(self) -> None:
        kind = classify_failure(message="Insufficient BASE balance. Have: 0.0")
        self.assertEqual(kind, FailureKind.INSUFFICIENT_BALANCE)

    def test_classifies_rate_limit(self) -> None:
        self.assertEqual(classify_failure(status_code=429), FailureKind.RATE_LIMITED)


if __name__ == "__main__":
    unittest.main()

