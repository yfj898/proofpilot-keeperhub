from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from demo_proofpilot import (  # noqa: E402
    _choose_attack_category,
    _choose_target_category,
    _semantic_deviations,
    parse_args,
)
from proofpilot.aave_adapter import AAVE_BASE_SEPOLIA_POOL  # noqa: E402
from proofpilot.intent import IntentAction, ProposedAction  # noqa: E402


class CompetitionDemoTests(unittest.TestCase):
    def test_default_target_forces_a_state_transition(self) -> None:
        self.assertEqual(_choose_target_category(0, None), 1)
        self.assertEqual(_choose_target_category(1, None), 0)

    def test_attack_prefers_semantic_noop(self) -> None:
        self.assertEqual(_choose_attack_category(0, 1), 0)
        self.assertEqual(_choose_attack_category(1, 0), 1)

    def test_attack_and_execute_cannot_be_combined(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--attack", "--execute"])

    def test_default_execution_mode_is_observe(self) -> None:
        args = parse_args([])
        self.assertEqual(args.execution_mode, "observe")

    def test_legacy_execute_maps_to_autonomous(self) -> None:
        args = parse_args(["--execute"])
        self.assertEqual(args.execution_mode, "autonomous")

    def test_confirm_flag_requires_confirm_mode(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--confirm"])

    def test_semantic_diagnosis_is_independent_of_defender_result(self) -> None:
        intended = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target=AAVE_BASE_SEPOLIA_POOL,
            function_signature="setUserEMode(uint8)",
            arguments=(1,),
            native_value=Decimal("0"),
        )
        observed = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target=AAVE_BASE_SEPOLIA_POOL,
            function_signature="setUserEMode(uint8)",
            arguments=(0,),
            native_value=Decimal("0"),
        )
        self.assertEqual(_semantic_deviations(intended, observed), ["wrong_emode_category"])


if __name__ == "__main__":
    unittest.main()
