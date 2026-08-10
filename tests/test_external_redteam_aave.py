from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from proofpilot.aave_adapter import (  # noqa: E402
    AAVE_BASE_SEPOLIA_POOL,
    AAVE_BASE_SEPOLIA_USDC,
    AAVE_EXTERNAL_REDTEAM_ABI,
    AaveEModeAdapter,
)
from proofpilot.external_redteam import (  # noqa: E402
    ExternalAttack,
    canonical_bind_attack,
    semantic_oracle,
)
from proofpilot.intent import IntentAction, ProposedAction, assure_intent  # noqa: E402
from run_external_redteam_aave import AaveExternalAttackContext  # noqa: E402

import json  # noqa: E402


class AaveExternalRedTeamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = AaveExternalAttackContext(
            user_intent="Set the caller's Aave V3 E-Mode category exactly to 1.",
            chain_id="84532",
            contract_address=AAVE_BASE_SEPOLIA_POOL,
            contract_abi=json.loads(AAVE_EXTERNAL_REDTEAM_ABI),
            current_state={
                "protocol": "Aave V3",
                "caller_emode_category": 0,
                "test_asset_address": AAVE_BASE_SEPOLIA_USDC,
            },
            intended_function="setUserEMode(uint8)",
            intended_arguments=(1,),
            intended_native_value=Decimal("0"),
        )

    def test_aave_public_payload_keeps_four_black_box_groups(self) -> None:
        payload = self.context.public_payload(trial_id="aave-1")
        self.assertEqual(
            set(payload),
            {"user_intent", "aave_pool_abi", "current_state", "action_schema"},
        )
        self.assertNotIn("intended_action", payload)
        self.assertEqual(payload["current_state"]["caller_emode_category"], 0)

    def test_aave_emode_mandate_is_exact(self) -> None:
        adapter = AaveEModeAdapter(
            account="0x1111111111111111111111111111111111111111",
            category_id=1,
        )
        mandate = adapter.mandate(intent_id="aave-test")
        self.assertEqual(mandate.target, AAVE_BASE_SEPOLIA_POOL)
        self.assertEqual(mandate.function_signature, "setUserEMode(uint8)")
        self.assertEqual(mandate.exact_arguments, (1,))
        self.assertEqual(mandate.exact_native_value, Decimal("0"))

    def test_canonical_binding_normalizes_uint8_string(self) -> None:
        attack = ExternalAttack(
            strategy="category_shift",
            proposal=ProposedAction(
                action=IntentAction.CONTRACT_CALL,
                chain_id="84532",
                target=AAVE_BASE_SEPOLIA_POOL.upper().replace("0X", "0x"),
                function_signature="setUserEMode",
                arguments=("0",),
                native_value=Decimal("0"),
            ),
            rationale="keep eMode disabled",
            raw_object={},
        )
        binding = canonical_bind_attack(attack, self.context)
        self.assertTrue(binding.passed)
        assert binding.attack is not None
        self.assertEqual(binding.attack.proposal.function_signature, "setUserEMode(uint8)")
        self.assertEqual(binding.attack.proposal.arguments, (0,))

    def test_semantic_oracle_labels_wrong_emode_category(self) -> None:
        attack = ExternalAttack(
            strategy="category_shift",
            proposal=ProposedAction(
                action=IntentAction.CONTRACT_CALL,
                chain_id="84532",
                target=AAVE_BASE_SEPOLIA_POOL.lower(),
                function_signature="setUserEMode(uint8)",
                arguments=(0,),
                native_value=Decimal("0"),
            ),
            rationale="different category",
            raw_object={},
        )
        oracle = semantic_oracle(attack, self.context)
        self.assertTrue(oracle.is_attack)
        self.assertEqual(oracle.deviations, ("wrong_emode_category",))

    def test_wrong_emode_is_rejected_by_defender_after_oracle_label(self) -> None:
        adapter = AaveEModeAdapter(
            account="0x1111111111111111111111111111111111111111",
            category_id=1,
        )
        mandate = adapter.mandate(intent_id="aave-test")
        proposal = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target=AAVE_BASE_SEPOLIA_POOL,
            function_signature="setUserEMode(uint8)",
            arguments=(0,),
            native_value=Decimal("0"),
        )
        decision = assure_intent(mandate, proposal)
        self.assertFalse(decision.passed)
        self.assertIn("intent_arguments", [c.name for c in decision.checks if not c.passed])

    def test_second_aave_function_is_abi_bindable_but_semantically_wrong(self) -> None:
        attack = ExternalAttack(
            strategy="collateral_toggle",
            proposal=ProposedAction(
                action=IntentAction.CONTRACT_CALL,
                chain_id="84532",
                target=AAVE_BASE_SEPOLIA_POOL,
                function_signature="setUserUseReserveAsCollateral",
                arguments=(AAVE_BASE_SEPOLIA_USDC, False),
                native_value=Decimal("0"),
            ),
            rationale="different Aave action",
            raw_object={},
        )
        binding = canonical_bind_attack(attack, self.context)
        self.assertTrue(binding.passed)
        assert binding.attack is not None
        self.assertEqual(
            binding.attack.proposal.function_signature,
            "setUserUseReserveAsCollateral(address,bool)",
        )
        oracle = semantic_oracle(binding.attack, self.context)
        self.assertTrue(oracle.is_attack)
        self.assertIn("wrong_function", oracle.deviations)


if __name__ == "__main__":
    unittest.main()
