from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.intent import (  # noqa: E402
    IntentAction,
    IntentMandate,
    ProposedAction,
    StateCondition,
    assure_intent,
    verify_state_snapshot_fresh,
    verify_state_conditions,
)


TARGET = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"


class IntentAssuranceTests(unittest.TestCase):
    def test_exact_transfer_passes(self) -> None:
        mandate = IntentMandate(
            intent_id="t1",
            action=IntentAction.TRANSFER_NATIVE,
            target=TARGET,
            exact_amount=Decimal("0.000001"),
        )
        proposal = ProposedAction(
            action=IntentAction.TRANSFER_NATIVE,
            chain_id="84532",
            target=TARGET,
            amount=Decimal("0.000001"),
        )
        self.assertTrue(assure_intent(mandate, proposal).passed)

    def test_wrong_target_is_rejected(self) -> None:
        mandate = IntentMandate(intent_id="t2", target=TARGET)
        proposal = ProposedAction(
            action=IntentAction.TRANSFER_NATIVE,
            chain_id="84532",
            target=OTHER,
            amount=Decimal("0.000001"),
        )
        result = assure_intent(mandate, proposal)
        self.assertFalse(result.passed)
        self.assertIn("Proposal target differs", " ".join(result.reasons))

    def test_wrong_contract_argument_is_rejected(self) -> None:
        mandate = IntentMandate(
            intent_id="c1",
            action=IntentAction.CONTRACT_CALL,
            target=TARGET,
            function_signature="setThreshold(uint256)",
            exact_arguments=(20,),
        )
        proposal = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target=TARGET,
            function_signature="setThreshold(uint256)",
            arguments=(200,),
        )
        self.assertFalse(assure_intent(mandate, proposal).passed)

    def test_forbidden_collateral_effect_is_explicitly_rejected(self) -> None:
        mandate = IntentMandate(
            intent_id="c2",
            action=IntentAction.CONTRACT_CALL,
            target=TARGET,
            function_signature="setUserUseReserveAsCollateral(address,bool)",
            forbidden_effects=("aave.collateral_configuration",),
        )
        proposal = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target=TARGET,
            function_signature="setUserUseReserveAsCollateral(address,bool)",
            arguments=(OTHER, False),
        )
        result = assure_intent(mandate, proposal)
        self.assertFalse(result.passed)
        self.assertIn("intent_forbidden_effects", [row.name for row in result.checks])

    def test_pre_and_postconditions_use_structured_state(self) -> None:
        conditions = (
            StateCondition("config.threshold", "eq", 20),
            StateCondition("config.paused", "eq", False),
        )
        result = verify_state_conditions(
            conditions,
            {"config": {"threshold": 20, "paused": False}},
            phase="post",
        )
        self.assertTrue(result.passed)

    def test_missing_state_fails_closed(self) -> None:
        result = verify_state_conditions(
            (StateCondition("config.threshold", "eq", 20),),
            {},
            phase="post",
        )
        self.assertFalse(result.passed)

    def test_snapshot_freshness_detects_drift(self) -> None:
        result = verify_state_snapshot_fresh(
            {"config": {"number": 20, "paused": False}},
            {"config": {"number": 21, "paused": False}},
        )
        self.assertFalse(result.passed)

    def test_snapshot_freshness_accepts_same_expected_leaves(self) -> None:
        result = verify_state_snapshot_fresh(
            {"config": {"number": 20}},
            {"config": {"number": 20, "extra": "ignored"}},
        )
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()

