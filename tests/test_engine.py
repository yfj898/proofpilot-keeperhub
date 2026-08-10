from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.engine import ProofPilotEngine  # noqa: E402
from proofpilot.mcp import McpError  # noqa: E402
from proofpilot.models import ActionKind, ExecutionPlan, RecoveryAction, RunState  # noqa: E402


RECIPIENT = "0x1111111111111111111111111111111111111111"


def valid_plan(**changes: object) -> ExecutionPlan:
    values = {
        "action": ActionKind.TRANSFER_NATIVE,
        "chain_id": "84532",
        "recipient": RECIPIENT,
        "amount": Decimal("0.000001"),
    }
    values.update(changes)
    return ExecutionPlan(**values)  # type: ignore[arg-type]


class FakeExecutor:
    def __init__(self, result: dict | Exception):
        self.result = result
        self.calls = 0

    def simulate_native_transfer(self, *, recipient: str, amount: str) -> dict:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class EngineTests(unittest.TestCase):
    def test_policy_rejection_never_calls_keeperhub(self) -> None:
        executor = FakeExecutor({"success": True, "status": "simulated", "wouldRevert": False})
        outcome = ProofPilotEngine(executor).admit_and_simulate(valid_plan(chain_id="8453"))
        self.assertEqual(outcome.state, RunState.POLICY_REJECTED)
        self.assertEqual(executor.calls, 0)
        self.assertEqual(outcome.recovery.action, RecoveryAction.STOP)

    def test_success_reaches_simulated(self) -> None:
        executor = FakeExecutor({"success": True, "status": "simulated", "wouldRevert": False})
        outcome = ProofPilotEngine(executor).admit_and_simulate(valid_plan())
        self.assertEqual(outcome.state, RunState.SIMULATED)
        self.assertEqual(executor.calls, 1)
        self.assertTrue(outcome.verification.passed)
        self.assertIsNone(outcome.recovery)

    def test_insufficient_balance_enters_safe_recovery(self) -> None:
        executor = FakeExecutor(
            McpError(
                "KeeperHub tool execute_transfer reported an error.",
                status=400,
                body={"code": "insufficient_balance", "error": "Insufficient BASE balance"},
            )
        )
        outcome = ProofPilotEngine(executor).admit_and_simulate(valid_plan())
        self.assertEqual(outcome.state, RunState.SIMULATION_FAILED)
        self.assertEqual(outcome.recovery.action, RecoveryAction.STOP)
        self.assertFalse(outcome.recovery.safe_to_repeat_write)

    def test_malformed_simulation_fails_closed(self) -> None:
        executor = FakeExecutor({"success": True, "status": "simulated"})
        outcome = ProofPilotEngine(executor).admit_and_simulate(valid_plan())
        self.assertEqual(outcome.state, RunState.SIMULATION_FAILED)
        self.assertFalse(outcome.verification.passed)


if __name__ == "__main__":
    unittest.main()

