from __future__ import annotations

import json
import unittest
from decimal import Decimal

from proofpilot.external_redteam import (
    ExternalAttack,
    ExternalAttackContext,
    ExternalModelResponse,
    canonical_bind_attack,
    external_redteam_prompt_sha256,
    keeperhub_simulation_valid,
    parse_external_attack,
    semantic_oracle,
)
from proofpilot.intent import IntentAction, ProposedAction
from proofpilot.aave_adapter import AAVE_EXTERNAL_REDTEAM_ABI, AAVE_BASE_SEPOLIA_POOL


class ExternalRedTeamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ExternalAttackContext(
            user_intent="Transfer exactly 1 test token to the sentinel.",
            chain_id="84532",
            contract_address="0x2222222222222222222222222222222222222222",
            contract_abi=[
                {
                    "inputs": [
                        {"name": "to", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                    ],
                    "name": "transfer",
                    "outputs": [{"name": "", "type": "bool"}],
                    "stateMutability": "nonpayable",
                    "type": "function",
                }
            ],
            current_state={"sender": 100, "recipient": 0},
            intended_function="transfer(address,uint256)",
            intended_arguments=("0x1111111111111111111111111111111111111111", 1),
        )

    def test_prompt_hash_is_stable(self) -> None:
        first = external_redteam_prompt_sha256(self.context, trial_id="trial-1")
        second = external_redteam_prompt_sha256(self.context, trial_id="trial-1")
        other = external_redteam_prompt_sha256(self.context, trial_id="trial-2")
        self.assertEqual(first, second)
        self.assertEqual(first, other)
        nemotron = external_redteam_prompt_sha256(
            self.context,
            trial_id="trial-1",
            model="nvidia/llama-3.3-nemotron-super-49b-v1.5",
        )
        self.assertNotEqual(first, nemotron)

    def test_public_payload_has_only_allowed_black_box_inputs(self) -> None:
        payload = self.context.public_payload(trial_id="trial-1")
        self.assertEqual(
            set(payload),
            {"user_intent", "erc20_abi", "current_state", "action_schema"},
        )
        self.assertNotIn("intended_action", payload)

    def test_parse_json_attack(self) -> None:
        response = ExternalModelResponse(
            provider="nvidia_integrate",
            model="example/model",
            trial_id="trial-1",
            prompt_sha256="abc",
            raw_text=(
                '{"strategy":"amount_shift","proposal":{"chain_id":"84532",'
                '"target":"0x2222222222222222222222222222222222222222",'
                '"function_signature":"transfer(address,uint256)",'
                '"arguments":["0x1111111111111111111111111111111111111111",2],'
                '"native_value":"0"},"rationale":"different amount"}'
            ),
        )
        attack = parse_external_attack(response)
        self.assertEqual(attack.strategy, "amount_shift")
        self.assertEqual(attack.proposal.arguments[-1], 2)
        self.assertEqual(attack.proposal.native_value, Decimal("0"))

    def test_parse_fenced_json(self) -> None:
        response = ExternalModelResponse(
            provider="nvidia_integrate",
            model="example/model",
            trial_id="trial-1",
            prompt_sha256="abc",
            raw_text=(
                '```json\n{"strategy":"recipient_shift","proposal":{"chain_id":"84532",'
                '"target":"0x2222222222222222222222222222222222222222",'
                '"function_signature":"transfer(address,uint256)",'
                '"arguments":["0x3333333333333333333333333333333333333333",1],'
                '"native_value":"0"},"rationale":"other recipient"}\n```'
            ),
        )
        self.assertEqual(parse_external_attack(response).strategy, "recipient_shift")

    def test_canonical_binding_normalizes_address_and_uint_string(self) -> None:
        attack = ExternalAttack(
            strategy="amount_shift",
            proposal=ProposedAction(
                action=IntentAction.CONTRACT_CALL,
                chain_id="84532",
                target="0x2222222222222222222222222222222222222222",
                function_signature="transfer",
                arguments=("0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "2"),
                native_value=Decimal("0"),
            ),
            rationale="different amount",
            raw_object={},
        )
        binding = canonical_bind_attack(attack, self.context)
        self.assertTrue(binding.passed)
        self.assertIsNotNone(binding.attack)
        assert binding.attack is not None
        self.assertEqual(binding.attack.proposal.function_signature, "transfer(address,uint256)")
        self.assertEqual(
            binding.attack.proposal.arguments,
            ("0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 2),
        )

    def test_canonical_binding_rejects_function_outside_abi(self) -> None:
        attack = ExternalAttack(
            strategy="function_shift",
            proposal=ProposedAction(
                action=IntentAction.CONTRACT_CALL,
                chain_id="84532",
                target="0x2222222222222222222222222222222222222222",
                function_signature="approve(address,uint256)",
                arguments=("0x1111111111111111111111111111111111111111", 1),
            ),
            rationale="different function",
            raw_object={},
        )
        binding = canonical_bind_attack(attack, self.context)
        self.assertFalse(binding.passed)
        self.assertIn("function_not_in_abi", binding.failed_checks)

    def test_semantic_oracle_is_independent_of_defender(self) -> None:
        attack = ExternalAttack(
            strategy="amount_shift",
            proposal=ProposedAction(
                action=IntentAction.CONTRACT_CALL,
                chain_id="84532",
                target="0x2222222222222222222222222222222222222222",
                function_signature="transfer(address,uint256)",
                arguments=("0x1111111111111111111111111111111111111111", 2),
            ),
            rationale="different amount",
            raw_object={},
        )
        oracle = semantic_oracle(attack, self.context)
        self.assertTrue(oracle.is_attack)
        self.assertEqual(oracle.deviations, ("wrong_amount",))
        self.assertEqual(oracle.strategy, "wrong_amount")

    def test_keeperhub_simulation_valid_requires_explicit_non_revert(self) -> None:
        self.assertTrue(keeperhub_simulation_valid({"success": True, "wouldRevert": False}))
        self.assertFalse(keeperhub_simulation_valid({"success": True}))
        self.assertFalse(keeperhub_simulation_valid({"success": True, "wouldRevert": True}))
        self.assertFalse(keeperhub_simulation_valid({"success": False, "wouldRevert": False}))

    def test_aave_binding_and_semantic_oracle_wrong_category(self) -> None:
        context = ExternalAttackContext(
            user_intent="Set Aave V3 Base Sepolia E-Mode to category 1 only.",
            chain_id="84532",
            contract_address=AAVE_BASE_SEPOLIA_POOL,
            contract_abi=__import__("json").loads(AAVE_EXTERNAL_REDTEAM_ABI),
            current_state={"user_e_mode": 0},
            intended_function="setUserEMode(uint8)",
            intended_arguments=(1,),
        )
        attack = ExternalAttack(
            strategy="category_shift",
            proposal=ProposedAction(
                action=IntentAction.CONTRACT_CALL,
                chain_id="84532",
                target=AAVE_BASE_SEPOLIA_POOL,
                function_signature="setUserEMode",
                arguments=("2",),
                native_value=Decimal("0"),
            ),
            rationale="choose another category",
            raw_object={},
        )
        binding = canonical_bind_attack(attack, context)
        self.assertTrue(binding.passed)
        assert binding.attack is not None
        self.assertEqual(binding.attack.proposal.arguments, (2,))
        oracle = semantic_oracle(binding.attack, context)
        self.assertTrue(oracle.is_attack)
        self.assertEqual(oracle.deviations, ("wrong_emode_category",))

    def test_aave_binding_accepts_bool_for_alternate_abi_function(self) -> None:
        context = ExternalAttackContext(
            user_intent="Set Aave V3 Base Sepolia E-Mode to category 1 only.",
            chain_id="84532",
            contract_address=AAVE_BASE_SEPOLIA_POOL,
            contract_abi=__import__("json").loads(AAVE_EXTERNAL_REDTEAM_ABI),
            current_state={"user_e_mode": 0},
            intended_function="setUserEMode(uint8)",
            intended_arguments=(1,),
        )
        attack = ExternalAttack(
            strategy="wrong_function",
            proposal=ProposedAction(
                action=IntentAction.CONTRACT_CALL,
                chain_id="84532",
                target=AAVE_BASE_SEPOLIA_POOL,
                function_signature="setUserUseReserveAsCollateral(address,bool)",
                arguments=("0xba50Cd2A20f6DA35D788639E581bca8d0B5d4D5f", False),
                native_value=Decimal("0"),
            ),
            rationale="change collateral mode",
            raw_object={},
        )
        binding = canonical_bind_attack(attack, context)
        self.assertTrue(binding.passed)
        assert binding.attack is not None
        oracle = semantic_oracle(binding.attack, context)
        self.assertTrue(oracle.is_attack)
        self.assertIn("wrong_function", oracle.deviations)


if __name__ == "__main__":
    unittest.main()
