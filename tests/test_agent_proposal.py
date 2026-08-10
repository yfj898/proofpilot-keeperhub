from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from agent_proposal import (  # noqa: E402
    AgentCandidate,
    AgentProposalError,
    agent_prompt_sha256,
    build_agent_payload,
    candidate_to_proposed_action,
    compact_keeperhub_tools,
)
from proofpilot.aave_adapter import (  # noqa: E402
    AAVE_BASE_SEPOLIA_POOL,
    AAVE_BASE_SEPOLIA_USDC,
    AAVE_EXTERNAL_REDTEAM_ABI,
)


class AgentProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.abi = json.loads(AAVE_EXTERNAL_REDTEAM_ABI)
        self.tools = [
            {"name": "execute_contract_call", "description": "Call a contract."},
            {"name": "get_direct_execution_status", "description": "Get status."},
            {"name": "delete_workflow", "description": "Irrelevant to this demo."},
        ]

    def candidate(self, proposal: dict[str, object]) -> AgentCandidate:
        return AgentCandidate(
            decision="propose",
            execution_tool="execute_contract_call",
            proposal=proposal,
            reason="bounded proposal",
            requested_model="test-model",
            provider_model="test-model",
            prompt_sha256="a" * 64,
            raw_response="{}",
        )

    def test_live_tool_inventory_is_compacted_without_inventing_tools(self) -> None:
        rows = compact_keeperhub_tools(self.tools)
        self.assertEqual(
            [row["name"] for row in rows],
            ["execute_contract_call", "get_direct_execution_status"],
        )

    def test_prompt_hash_is_deterministic(self) -> None:
        payload = build_agent_payload(
            user_intent="Set E-Mode to 1",
            current_state={"chain_id": "84532", "caller_emode_category": 0},
            discovered_tools=compact_keeperhub_tools(self.tools),
            contract_abi=self.abi,
        )
        self.assertEqual(agent_prompt_sha256(payload), agent_prompt_sha256(payload))

    def test_correct_candidate_binds_to_proposed_action(self) -> None:
        candidate = self.candidate(
            {
                "chain_id": "84532",
                "target": AAVE_BASE_SEPOLIA_POOL.upper().replace("0X", "0x"),
                "function_signature": "setUserEMode",
                "arguments": ["1"],
                "native_value": "0",
            }
        )
        action = candidate_to_proposed_action(
            candidate,
            contract_abi=self.abi,
            discovered_tool_names={"execute_contract_call", "get_direct_execution_status"},
        )
        self.assertEqual(action.function_signature, "setUserEMode(uint8)")
        self.assertEqual(action.arguments, (1,))
        self.assertEqual(action.target, AAVE_BASE_SEPOLIA_POOL.lower())

    def test_json_string_arguments_are_shape_normalized_without_broadening(self) -> None:
        candidate = self.candidate(
            {
                "chain_id": "84532",
                "target": AAVE_BASE_SEPOLIA_POOL,
                "function_signature": "setUserEMode(uint8)",
                "arguments": '["1"]',
                "native_value": "0",
            }
        )
        action = candidate_to_proposed_action(
            candidate,
            contract_abi=self.abi,
            discovered_tool_names={"execute_contract_call"},
        )
        self.assertEqual(action.arguments, (1,))

    def test_wrong_aave_function_remains_semantically_visible(self) -> None:
        candidate = self.candidate(
            {
                "chain_id": "84532",
                "target": AAVE_BASE_SEPOLIA_POOL,
                "function_signature": "setUserUseReserveAsCollateral",
                "arguments": [AAVE_BASE_SEPOLIA_USDC, False],
                "native_value": "0",
            }
        )
        action = candidate_to_proposed_action(
            candidate,
            contract_abi=self.abi,
            discovered_tool_names={"execute_contract_call"},
        )
        self.assertEqual(
            action.function_signature,
            "setUserUseReserveAsCollateral(address,bool)",
        )

    def test_undiscovered_execution_tool_fails_closed(self) -> None:
        candidate = AgentCandidate(
            decision="propose",
            execution_tool="execute_magic",
            proposal={
                "chain_id": "84532",
                "target": AAVE_BASE_SEPOLIA_POOL,
                "function_signature": "setUserEMode(uint8)",
                "arguments": [1],
                "native_value": "0",
            },
            reason="bad tool",
            requested_model="test-model",
            provider_model="test-model",
            prompt_sha256="a" * 64,
            raw_response="{}",
        )
        with self.assertRaises(AgentProposalError):
            candidate_to_proposed_action(
                candidate,
                contract_abi=self.abi,
                discovered_tool_names={"execute_contract_call"},
            )


if __name__ == "__main__":
    unittest.main()
