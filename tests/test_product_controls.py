from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from product_controls import (  # noqa: E402
    build_intent_preview,
    decide_broadcast,
    render_intent_preview,
    resolve_execution_mode,
)
from proofpilot.aave_adapter import AAVE_BASE_SEPOLIA_POOL  # noqa: E402
from proofpilot.intent import IntentAction, ProposedAction  # noqa: E402


class ProductControlsTests(unittest.TestCase):
    def proposal(self) -> ProposedAction:
        return ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target=AAVE_BASE_SEPOLIA_POOL,
            function_signature="setUserEMode(uint8)",
            arguments=(1,),
            native_value=Decimal("0"),
        )

    def test_default_mode_is_observe(self) -> None:
        self.assertEqual(resolve_execution_mode(requested_mode=None, legacy_execute=False), "observe")
        self.assertEqual(resolve_execution_mode(requested_mode=None, legacy_execute=True), "autonomous")

    def test_observe_never_broadcasts(self) -> None:
        decision = decide_broadcast(
            mode="observe", explicit_confirm=True, interactive=True, input_func=lambda _: "yes"
        )
        self.assertFalse(decision.allowed)

    def test_confirm_requires_explicit_or_interactive_human_action(self) -> None:
        self.assertFalse(
            decide_broadcast(
                mode="confirm", explicit_confirm=False, interactive=False
            ).allowed
        )
        self.assertTrue(
            decide_broadcast(
                mode="confirm", explicit_confirm=True, interactive=False
            ).allowed
        )

    def test_autonomous_allows_only_after_upstream_gates_call_it(self) -> None:
        decision = decide_broadcast(
            mode="autonomous", explicit_confirm=False, interactive=False
        )
        self.assertTrue(decision.allowed)

    def test_preview_is_human_readable_and_explicit(self) -> None:
        preview = build_intent_preview(
            user_intent="Set my Aave E-Mode category exactly to 1",
            proposal=self.proposal(),
            current_emode=0,
            execution_mode="confirm",
            network_name="Base Sepolia",
        )
        text = render_intent_preview(preview)
        self.assertIn("0 -> 1", text)
        self.assertIn("Native ETH sent: 0", text)
        self.assertIn("Collateral settings: unchanged", text)
        self.assertIn("Execution mode: CONFIRM", text)


if __name__ == "__main__":
    unittest.main()

