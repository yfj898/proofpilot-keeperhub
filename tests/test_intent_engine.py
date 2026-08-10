from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.intent import IntentAction, IntentMandate, ProposedAction, StateCondition  # noqa: E402
from proofpilot.intent_engine import IntentAssuranceEngine  # noqa: E402


TARGET = "0x1111111111111111111111111111111111111111"


class FakeSimulator:
    def __init__(self) -> None:
        self.calls = 0

    def simulate_contract_call(self, **kwargs):
        self.calls += 1
        return {
            "success": True,
            "status": "simulated",
            "wouldRevert": False,
            "to": kwargs["contract_address"],
            "from": "0x9999999999999999999999999999999999999999",
            "value": "0",
        }


class IntentEngineTests(unittest.TestCase):
    def _mandate(self) -> IntentMandate:
        return IntentMandate(
            intent_id="demo",
            action=IntentAction.CONTRACT_CALL,
            target=TARGET,
            function_signature="setThreshold(uint256)",
            exact_arguments=(20,),
            preconditions=(StateCondition("config.paused", "eq", False),),
        )

    def _proposal(self) -> ProposedAction:
        return ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target=TARGET,
            function_signature="setThreshold(uint256)",
            arguments=(20,),
        )

    def test_safe_contract_proposal_reaches_simulation(self) -> None:
        simulator = FakeSimulator()
        outcome = IntentAssuranceEngine(simulator).admit_contract_call(
            self._mandate(),
            self._proposal(),
            pre_state={"config": {"paused": False}},
            abi="[]",
        )
        self.assertTrue(outcome.approved)
        self.assertEqual(simulator.calls, 1)
        self.assertTrue(outcome.execution_payload_sha256)
        self.assertTrue(outcome.simulation_binding_check and outcome.simulation_binding_check.passed)

    def test_wrong_argument_never_reaches_keeperhub(self) -> None:
        simulator = FakeSimulator()
        bad = replace(self._proposal(), arguments=(200,))
        outcome = IntentAssuranceEngine(simulator).admit_contract_call(
            self._mandate(), bad, pre_state={"config": {"paused": False}}, abi="[]"
        )
        self.assertFalse(outcome.approved)
        self.assertEqual(simulator.calls, 0)

    def test_stale_precondition_never_reaches_keeperhub(self) -> None:
        simulator = FakeSimulator()
        outcome = IntentAssuranceEngine(simulator).admit_contract_call(
            self._mandate(),
            self._proposal(),
            pre_state={"config": {"paused": True}},
            abi="[]",
        )
        self.assertFalse(outcome.approved)
        self.assertEqual(simulator.calls, 0)


if __name__ == "__main__":
    unittest.main()
