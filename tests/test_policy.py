from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.models import ActionKind, ExecutionPlan  # noqa: E402
from proofpilot.policy import PolicyConfig, PolicyEngine  # noqa: E402


RECIPIENT = "0x1111111111111111111111111111111111111111"
WALLET = "0x2222222222222222222222222222222222222222"


def plan(**changes: object) -> ExecutionPlan:
    values = {
        "action": ActionKind.TRANSFER_NATIVE,
        "chain_id": "84532",
        "recipient": RECIPIENT,
        "amount": Decimal("0.000001"),
    }
    values.update(changes)
    return ExecutionPlan(**values)  # type: ignore[arg-type]


class PolicyTests(unittest.TestCase):
    def test_accepts_small_base_sepolia_transfer(self) -> None:
        decision = PolicyEngine().evaluate(plan())
        self.assertTrue(decision.passed, decision.reasons)

    def test_rejects_mainnet(self) -> None:
        decision = PolicyEngine().evaluate(plan(chain_id="8453"))
        self.assertFalse(decision.passed)
        self.assertIn("chain_id=8453 is not in the testnet allowlist.", decision.reasons)

    def test_rejects_cap_violation(self) -> None:
        decision = PolicyEngine().evaluate(plan(amount=Decimal("0.01")))
        self.assertFalse(decision.passed)

    def test_rejects_recipient_not_allowlisted(self) -> None:
        config = PolicyConfig(
            require_recipient_allowlist=True,
            allowed_recipients=frozenset({WALLET}),
        )
        decision = PolicyEngine(config).evaluate(plan())
        self.assertFalse(decision.passed)

    def test_rejects_self_transfer_product_path(self) -> None:
        config = PolicyConfig(wallet_address=RECIPIENT, allow_self_transfer=False)
        decision = PolicyEngine(config).evaluate(plan())
        self.assertFalse(decision.passed)


if __name__ == "__main__":
    unittest.main()

