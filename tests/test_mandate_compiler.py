from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.aave_adapter import (  # noqa: E402
    AAVE_BASE_SEPOLIA_POOL,
    AAVE_BASE_SEPOLIA_WETH_GATEWAY,
    AAVE_DEPOSIT_ETH_ABI,
    AAVE_SET_USER_EMODE_ABI,
)
from proofpilot.intent_ir import DelegationEnvelope  # noqa: E402
from proofpilot.mandate_compiler import BindingProfile, CompilationError, MandateCompiler  # noqa: E402


ACCOUNT = "0x1111111111111111111111111111111111111111"
TOKEN = "0x2222222222222222222222222222222222222222"
STORAGE = "0x3333333333333333333333333333333333333333"


def compiler() -> MandateCompiler:
    return MandateCompiler(
        {
            "storage": BindingProfile("storage", "storage", STORAGE, "storeNumber(uint256)"),
            "erc20": BindingProfile("erc20", "erc20", TOKEN, "transfer(address,uint256)", decimals=6),
            "aave": BindingProfile(
                "aave",
                "aave",
                AAVE_BASE_SEPOLIA_WETH_GATEWAY,
                "depositETH(address,address,uint16)",
                AAVE_DEPOSIT_ETH_ABI,
                argument_prefix=(AAVE_BASE_SEPOLIA_POOL,),
                argument_suffix=(0,),
            ),
            "aave_emode": BindingProfile(
                "aave_emode",
                "aave",
                AAVE_BASE_SEPOLIA_POOL,
                "setUserEMode(uint8)",
                AAVE_SET_USER_EMODE_ABI,
            ),
        }
    )


class MandateCompilerTests(unittest.TestCase):
    def test_compiles_aave_natural_language_with_binding(self) -> None:
        delegation = DelegationEnvelope(
            delegation_id="aave-demo",
            allowed_protocols=frozenset({"aave"}),
            allowed_targets=frozenset({AAVE_BASE_SEPOLIA_WETH_GATEWAY}),
            allowed_functions=frozenset({"depositETH(address,address,uint16)"}),
            max_native_value=Decimal("0.001"),
        )
        intent = compiler().compile(
            "Supply 0.0001 ETH to Aave",
            delegation=delegation,
            account=ACCOUNT,
            nonce=7,
            intent_id="aave-natural-language-demo",
        )
        self.assertEqual(intent.intent_id, "aave-natural-language-demo")
        self.assertEqual(intent.action.arguments, (AAVE_BASE_SEPOLIA_POOL, ACCOUNT, 0))
        self.assertEqual(intent.action.native_value, Decimal("0.0001"))
        self.assertTrue(intent.source_text_hash)
        self.assertTrue(intent.parent_delegation_hash)

    def test_compiles_erc20_units_to_raw_amount(self) -> None:
        delegation = DelegationEnvelope(
            delegation_id="erc20-demo",
            allowed_protocols=frozenset({"erc20"}),
            allowed_targets=frozenset({TOKEN}),
            allowed_functions=frozenset({"transfer(address,uint256)"}),
        )
        intent = compiler().compile(
            f"Transfer 1.25 USDC to {ACCOUNT}",
            delegation=delegation,
            account=ACCOUNT,
            nonce=8,
        )
        self.assertEqual(intent.action.arguments, (ACCOUNT, 1_250_000))

    def test_compiles_aave_emode_with_exact_category_binding(self) -> None:
        delegation = DelegationEnvelope(
            delegation_id="aave-emode-demo",
            allowed_protocols=frozenset({"aave"}),
            allowed_targets=frozenset({AAVE_BASE_SEPOLIA_POOL}),
            allowed_functions=frozenset({"setUserEMode(uint8)"}),
            max_native_value=Decimal("0"),
        )
        intent = compiler().compile(
            "Set my Aave E-Mode category exactly to 1",
            delegation=delegation,
            account=ACCOUNT,
            nonce=9,
            intent_id="aave-emode-natural-language-demo",
        )
        self.assertEqual(intent.action.target, AAVE_BASE_SEPOLIA_POOL)
        self.assertEqual(intent.action.function_signature, "setUserEMode(uint8)")
        self.assertEqual(intent.action.arguments, (1,))
        self.assertEqual(intent.postconditions[0].path, "aave.user_emode")
        self.assertEqual(intent.postconditions[0].value, 1)

    def test_emode_rejects_unsupported_deadline_modifier(self) -> None:
        with self.assertRaises(CompilationError):
            compiler().compile(
                "On Base Sepolia chain 84532, set my Aave E-Mode category to 1, deadline 30",
                delegation=DelegationEnvelope(delegation_id="x"),
                account=ACCOUNT,
                nonce=10,
            )

    def test_emode_rejects_natural_language_time_deadline(self) -> None:
        with self.assertRaises(CompilationError):
            compiler().compile(
                "Set Aave E-Mode to 1 before 10pm",
                delegation=DelegationEnvelope(delegation_id="x"),
                account=ACCOUNT,
                nonce=10,
            )

    def test_emode_rejects_unsupported_mainnet_chain(self) -> None:
        with self.assertRaises(CompilationError):
            compiler().compile(
                "On Ethereum mainnet set Aave E-Mode to 1",
                delegation=DelegationEnvelope(delegation_id="x"),
                account=ACCOUNT,
                nonce=10,
            )

    def test_emode_from_to_transition_is_rejected_as_ambiguous(self) -> None:
        with self.assertRaises(CompilationError):
            compiler().compile(
                "Set my Aave E-Mode from 0 to 1",
                delegation=DelegationEnvelope(delegation_id="x"),
                account=ACCOUNT,
                nonce=1,
            )

    def test_emode_negated_numeric_alternative_is_rejected(self) -> None:
        with self.assertRaises(CompilationError):
            compiler().compile(
                "Do not set Aave E-Mode to 2; set it to 1",
                delegation=DelegationEnvelope(delegation_id="x"),
                account=ACCOUNT,
                nonce=1,
            )

    def test_emode_conflicting_categories_are_rejected(self) -> None:
        with self.assertRaises(CompilationError):
            compiler().compile(
                "Set Aave E-Mode category 1 and category 2",
                delegation=DelegationEnvelope(delegation_id="x"),
                account=ACCOUNT,
                nonce=1,
            )

    def test_category_conflict_without_protocol_name_is_rejected(self) -> None:
        with self.assertRaises(CompilationError):
            compiler().compile(
                "Set category 1 and category 2",
                delegation=DelegationEnvelope(delegation_id="x"),
                account=ACCOUNT,
                nonce=1,
            )

    def test_conditional_intent_is_rejected(self) -> None:
        with self.assertRaises(CompilationError):
            compiler().compile(
                "Set Aave E-Mode category 1 unless health factor falls below 2",
                delegation=DelegationEnvelope(delegation_id="x"),
                account=ACCOUNT,
                nonce=1,
            )

    def test_emode_category_ignores_earlier_chain_id(self) -> None:
        delegation = DelegationEnvelope(
            delegation_id="aave-emode-chain-id",
            allowed_protocols=frozenset({"aave"}),
            allowed_targets=frozenset({AAVE_BASE_SEPOLIA_POOL}),
            allowed_functions=frozenset({"setUserEMode(uint8)"}),
            max_native_value=Decimal("0"),
        )
        intent = compiler().compile(
            "On Base Sepolia chain 84532, set my Aave E-Mode category exactly to 1",
            delegation=delegation,
            account=ACCOUNT,
            nonce=10,
        )
        self.assertEqual(intent.action.arguments, (1,))
        self.assertEqual(intent.chain_id, "84532")

    def test_explicit_base_sepolia_emode_without_protocol_name_compiles(self) -> None:
        delegation = DelegationEnvelope(
            delegation_id="aave-emode-chain-id",
            allowed_protocols=frozenset({"aave"}),
            allowed_targets=frozenset({AAVE_BASE_SEPOLIA_POOL}),
            allowed_functions=frozenset({"setUserEMode(uint8)"}),
            max_native_value=Decimal("0"),
        )
        intent = compiler().compile(
            "On Base Sepolia chain 84532 set E-Mode category 1",
            delegation=delegation,
            account=ACCOUNT,
            nonce=10,
        )
        self.assertEqual(intent.action.arguments, (1,))
        self.assertEqual(intent.chain_id, "84532")

    def test_supply_amount_ignores_earlier_chain_id(self) -> None:
        delegation = DelegationEnvelope(
            delegation_id="aave-supply-chain-id",
            allowed_protocols=frozenset({"aave"}),
            allowed_targets=frozenset({AAVE_BASE_SEPOLIA_WETH_GATEWAY}),
            allowed_functions=frozenset({"depositETH(address,address,uint16)"}),
            max_native_value=Decimal("1"),
        )
        intent = compiler().compile(
            "On Base Sepolia chain 84532, supply 0.0001 ETH to Aave",
            delegation=delegation,
            account=ACCOUNT,
            nonce=11,
        )
        self.assertEqual(intent.action.native_value, Decimal("0.0001"))

    def test_ambiguous_text_fails_closed(self) -> None:
        with self.assertRaises(CompilationError):
            compiler().compile(
                "please optimize my position",
                delegation=DelegationEnvelope(delegation_id="x"),
                account=ACCOUNT,
                nonce=1,
            )


if __name__ == "__main__":
    unittest.main()
