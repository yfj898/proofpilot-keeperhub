from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .intent import IntentAction, IntentMandate, ProposedAction
from .models import CheckResult, VerificationResult
from .reader import BaseSepoliaReader, WEI_PER_ETH


# Canonical BGD/Aave Address Book deployment: Aave V3 Base Sepolia.
AAVE_BASE_SEPOLIA_POOL = "0x8bAB6d1b75f19e9eD9fCe8b9BD338844fF79aE27"
AAVE_BASE_SEPOLIA_WETH_GATEWAY = "0x0568130e794429D2eEBC4dafE18f25Ff1a1ed8b6"
AAVE_BASE_SEPOLIA_WETH_ATOKEN = "0x73a5bB60b0B0fc35710DDc0ea9c407031E31Bdbb"
AAVE_BASE_SEPOLIA_WETH_VTOKEN = "0x562abf6562d6A2b165aDa02b5946bc3E7b4dD653"
AAVE_BASE_SEPOLIA_USDC = "0xba50Cd2A20f6DA35D788639E581bca8d0B5d4D5f"

AAVE_DEPOSIT_ETH_ABI = json.dumps(
    [
        {
            "inputs": [
                {"name": "pool", "type": "address"},
                {"name": "onBehalfOf", "type": "address"},
                {"name": "referralCode", "type": "uint16"},
            ],
            "name": "depositETH",
            "outputs": [],
            "stateMutability": "payable",
            "type": "function",
        }
    ],
    separators=(",", ":"),
)

AAVE_SET_USER_EMODE_ABI = json.dumps(
    [
        {
            "inputs": [{"name": "categoryId", "type": "uint8"}],
            "name": "setUserEMode",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        }
    ],
    separators=(",", ":"),
)

AAVE_GET_USER_EMODE_ABI = json.dumps(
    [
        {
            "inputs": [{"name": "user", "type": "address"}],
            "name": "getUserEMode",
            "outputs": [{"name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        }
    ],
    separators=(",", ":"),
)


AAVE_EXTERNAL_REDTEAM_ABI = json.dumps(
    [
        {
            "inputs": [{"name": "categoryId", "type": "uint8"}],
            "name": "setUserEMode",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [
                {"name": "asset", "type": "address"},
                {"name": "useAsCollateral", "type": "bool"},
            ],
            "name": "setUserUseReserveAsCollateral",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        },
    ],
    separators=(",", ":"),
)


@dataclass(frozen=True)
class AaveEModeAdapter:
    """Intent adapter for Aave V3 Pool.setUserEMode on Base Sepolia."""

    account: str
    category_id: int
    name: str = "aave_v3_base_sepolia_set_user_emode"

    def __post_init__(self) -> None:
        if self.category_id < 0 or self.category_id > 255:
            raise ValueError("Aave eMode category_id must fit uint8")

    def mandate(self, *, intent_id: str) -> IntentMandate:
        return IntentMandate(
            intent_id=intent_id,
            action=IntentAction.CONTRACT_CALL,
            target=AAVE_BASE_SEPOLIA_POOL,
            function_signature="setUserEMode(uint8)",
            exact_arguments=(self.category_id,),
            exact_native_value=Decimal("0"),
            description=(
                "Set the exact Aave V3 Base Sepolia eMode category for the caller "
                "without attaching native ETH."
            ),
        )

    def proposal(self, mandate: IntentMandate) -> ProposedAction:
        return ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id=mandate.chain_id,
            target=AAVE_BASE_SEPOLIA_POOL,
            function_signature=mandate.function_signature,
            arguments=mandate.exact_arguments or (),
            native_value=Decimal("0"),
        )


@dataclass(frozen=True)
class AaveEthSupplyAdapter:
    account: str
    amount_eth: Decimal
    name: str = "aave_v3_base_sepolia_eth_supply"

    def mandate(self, *, intent_id: str) -> IntentMandate:
        return IntentMandate(
            intent_id=intent_id,
            action=IntentAction.CONTRACT_CALL,
            target=AAVE_BASE_SEPOLIA_WETH_GATEWAY,
            function_signature="depositETH(address,address,uint16)",
            exact_arguments=(AAVE_BASE_SEPOLIA_POOL, self.account, 0),
            exact_native_value=self.amount_eth,
            description=(
                "Supply the exact native test ETH amount to Aave V3 Base Sepolia "
                "without creating variable debt."
            ),
        )

    def proposal(self, mandate: IntentMandate) -> ProposedAction:
        return ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id=mandate.chain_id,
            target=AAVE_BASE_SEPOLIA_WETH_GATEWAY,
            function_signature=mandate.function_signature,
            arguments=mandate.exact_arguments or (),
            native_value=self.amount_eth,
        )

    def read_state(self, reader: BaseSepoliaReader, account: str = "") -> dict[str, Any]:
        return {
            "native": reader.get_native_balance(self.account),
            "a_weth": reader.erc20_balance_of(AAVE_BASE_SEPOLIA_WETH_ATOKEN, self.account),
            "variable_debt": reader.erc20_balance_of(AAVE_BASE_SEPOLIA_WETH_VTOKEN, self.account),
        }

    def verify_outcome(
        self,
        mandate: IntentMandate,
        pre: dict[str, Any],
        post: dict[str, Any],
    ) -> VerificationResult:
        expected_wei = int(self.amount_eth * WEI_PER_ETH)
        a_delta = int(post["a_weth"]) - int(pre["a_weth"])
        debt_delta = int(post["variable_debt"]) - int(pre["variable_debt"])
        checks = (
            CheckResult(
                "aave_atoken_increase",
                a_delta >= expected_wei,
                f"aWETH delta={a_delta}; expected at least {expected_wei}.",
            ),
            CheckResult(
                "aave_no_new_variable_debt",
                debt_delta == 0,
                f"Variable debt changed by {debt_delta}.",
            ),
        )
        return VerificationResult(all(check.passed for check in checks), checks)

    @staticmethod
    def deployment_addresses() -> tuple[str, ...]:
        return (
            AAVE_BASE_SEPOLIA_POOL,
            AAVE_BASE_SEPOLIA_WETH_GATEWAY,
            AAVE_BASE_SEPOLIA_WETH_ATOKEN,
            AAVE_BASE_SEPOLIA_WETH_VTOKEN,
            AAVE_BASE_SEPOLIA_USDC,
        )

