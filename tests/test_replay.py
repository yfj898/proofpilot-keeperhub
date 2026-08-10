from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.intent import IntentAction, IntentMandate, ProposedAction  # noqa: E402
from proofpilot.replay import IntentReplayGuard, proposal_fingerprint  # noqa: E402


TARGET = "0x1111111111111111111111111111111111111111"


class ReplayGuardTests(unittest.TestCase):
    def test_exact_replay_is_rejected(self) -> None:
        mandate = IntentMandate(
            intent_id="intent-1",
            action=IntentAction.CONTRACT_CALL,
            target=TARGET,
            function_signature="storeNumber(uint256)",
            exact_arguments=(20,),
        )
        proposal = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target=TARGET,
            function_signature="storeNumber(uint256)",
            arguments=(20,),
        )
        guard = IntentReplayGuard()
        self.assertTrue(guard.check(mandate, proposal).passed)
        guard.consume(mandate, proposal)
        self.assertFalse(guard.check(mandate, proposal).passed)

    def test_new_intent_id_is_allowed(self) -> None:
        proposal = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target=TARGET,
            function_signature="storeNumber(uint256)",
            arguments=(20,),
        )
        first = IntentMandate("intent-1", action=IntentAction.CONTRACT_CALL, target=TARGET)
        second = IntentMandate("intent-2", action=IntentAction.CONTRACT_CALL, target=TARGET)
        guard = IntentReplayGuard()
        guard.consume(first, proposal)
        self.assertTrue(guard.check(second, proposal).passed)

    def test_fingerprint_is_stable(self) -> None:
        mandate = IntentMandate("intent-1", action=IntentAction.CONTRACT_CALL, target=TARGET)
        proposal = ProposedAction(IntentAction.CONTRACT_CALL, "84532", TARGET)
        self.assertEqual(
            proposal_fingerprint(mandate, proposal),
            proposal_fingerprint(mandate, proposal),
        )


if __name__ == "__main__":
    unittest.main()
