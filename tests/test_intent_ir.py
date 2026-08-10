from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.intent_ir import (  # noqa: E402
    DelegationEnvelope,
    IntentEnvelope,
    IntentIRAction,
    delegation_hash,
    source_hash,
    verify_delegation,
)


TARGET = "0x1111111111111111111111111111111111111111"


class IntentIRTests(unittest.TestCase):
    def test_delegation_contains_submandate_and_commitment_is_stable(self) -> None:
        delegation = DelegationEnvelope(
            delegation_id="d1",
            allowed_protocols=frozenset({"aave"}),
            allowed_targets=frozenset({TARGET}),
            allowed_functions=frozenset({"depositETH(address,address,uint16)"}),
            max_native_value=Decimal("0.001"),
            expires_at=2_000_000_100,
        )
        intent = IntentEnvelope(
            intent_id="i1",
            source_text="supply 0.0001 ETH to Aave",
            action=IntentIRAction(
                protocol="aave",
                target=TARGET,
                function_signature="depositETH(address,address,uint16)",
                native_value=Decimal("0.0001"),
            ),
            deadline=2_000_000_050,
            source_text_hash=source_hash("supply 0.0001 ETH to Aave"),
            parent_delegation_hash=delegation_hash(delegation),
        )
        self.assertTrue(verify_delegation(delegation, intent, now=2_000_000_000).passed)
        self.assertEqual(intent.commitment(), intent.commitment())
        self.assertEqual(len(intent.commitment()), 64)
        self.assertEqual(intent.to_eip712_typed_data()["message"]["mandateHash"], "0x" + intent.commitment())

    def test_delegation_rejects_budget_expansion(self) -> None:
        delegation = DelegationEnvelope(delegation_id="d2", max_native_value=Decimal("0.001"))
        intent = IntentEnvelope(
            intent_id="i2",
            source_text="overspend",
            action=IntentIRAction(
                protocol="x",
                target=TARGET,
                function_signature="f()",
                native_value=Decimal("0.01"),
            ),
        )
        self.assertFalse(verify_delegation(delegation, intent, now=1).passed)


if __name__ == "__main__":
    unittest.main()

