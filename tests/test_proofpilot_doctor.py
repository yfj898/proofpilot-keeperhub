from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from proofpilot_doctor import (  # noqa: E402
    DOCTOR_READ_ONLY_TOOL_CALLS,
    _aave_protocol_actions,
    _agent_probe_matches_expected,
    _base_sepolia_is_stable,
    _final_status,
)
from proofpilot.aave_adapter import AAVE_BASE_SEPOLIA_POOL  # noqa: E402
from proofpilot.intent import IntentAction, ProposedAction  # noqa: E402
from decimal import Decimal


class ProofPilotDoctorTests(unittest.TestCase):
    def test_doctor_keeperhub_surface_is_read_only_discovery(self) -> None:
        self.assertEqual(
            DOCTOR_READ_ONLY_TOOL_CALLS,
            frozenset(
                {
                    "list_integrations",
                    "get_wallet_integration",
                    "list_action_schemas",
                    "search_protocol_actions",
                }
            ),
        )
        self.assertNotIn("execute_contract_call", DOCTOR_READ_ONLY_TOOL_CALLS)

    def test_base_sepolia_stable_chain_schema(self) -> None:
        self.assertTrue(
            _base_sepolia_is_stable(
                {"chains": [{"chainId": "84532", "status": "stable"}]}
            )
        )
        self.assertFalse(
            _base_sepolia_is_stable(
                {"chains": [{"chainId": "84532", "status": "experimental"}]}
            )
        )

    def test_aave_protocol_action_discovery(self) -> None:
        self.assertEqual(
            _aave_protocol_actions(
                {
                    "actions": [
                        {"actionType": "aave-v3/supply"},
                        {"actionType": "aave-v3/repay"},
                        {"actionType": "uniswap/swap"},
                    ]
                }
            ),
            ["aave-v3/repay", "aave-v3/supply"],
        )

    def test_ready_when_no_failures(self) -> None:
        self.assertEqual(
            _final_status([{"status": "PASS"}, {"status": "SKIP"}]),
            "READY",
        )

    def test_warning_is_visible_without_making_runtime_unusable(self) -> None:
        self.assertEqual(
            _final_status([{"status": "PASS"}, {"status": "WARN"}]),
            "READY_WITH_WARNINGS",
        )

    def test_transient_agent_probe_warning_does_not_equal_infrastructure_failure(self) -> None:
        self.assertEqual(
            _final_status(
                [
                    {"status": "PASS", "name": "keeperhub_mcp"},
                    {"status": "PASS", "name": "wallet_integration"},
                    {"status": "WARN", "name": "agent_live_probe"},
                ]
            ),
            "READY_WITH_WARNINGS",
        )

    def test_failure_is_not_ready(self) -> None:
        self.assertEqual(
            _final_status([{"status": "FAIL"}, {"status": "PASS"}]),
            "NOT_READY",
        )

    def test_agent_probe_requires_exact_known_readiness_action(self) -> None:
        good = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target=AAVE_BASE_SEPOLIA_POOL,
            function_signature="setUserEMode(uint8)",
            arguments=(1,),
            native_value=Decimal("0"),
        )
        wrong = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target=AAVE_BASE_SEPOLIA_POOL,
            function_signature="setUserEMode(uint8)",
            arguments=(0,),
            native_value=Decimal("0"),
        )
        self.assertTrue(_agent_probe_matches_expected(good))
        self.assertFalse(_agent_probe_matches_expected(wrong))


if __name__ == "__main__":
    unittest.main()

