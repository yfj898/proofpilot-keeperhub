from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .config import BASE_SEPOLIA_CHAIN_ID
from .models import ActionKind, CheckResult, ExecutionPlan, PolicyDecision


def looks_like_evm_address(value: str) -> bool:
    if len(value) != 42 or not value.startswith("0x"):
        return False
    try:
        int(value[2:], 16)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class PolicyConfig:
    allowed_chain_ids: frozenset[str] = frozenset({BASE_SEPOLIA_CHAIN_ID})
    max_native_amount: Decimal = Decimal("0.001")
    allowed_recipients: frozenset[str] = frozenset()
    require_recipient_allowlist: bool = False
    allow_self_transfer: bool = False
    wallet_address: str = ""


class PolicyEngine:
    """Deterministic transaction admission policy.

    This module intentionally contains no model calls and no KeeperHub calls. A plan
    either passes these checks or it never reaches simulation/execution.
    """

    def __init__(self, config: PolicyConfig | None = None):
        self.config = config or PolicyConfig()

    def evaluate(self, plan: ExecutionPlan) -> PolicyDecision:
        checks: list[CheckResult] = []

        checks.append(
            CheckResult(
                "supported_action",
                plan.action == ActionKind.TRANSFER_NATIVE,
                "Only native-token transfers are allowed in the MVP.",
            )
        )
        checks.append(
            CheckResult(
                "testnet_only",
                plan.chain_id in self.config.allowed_chain_ids,
                f"chain_id={plan.chain_id} is not in the testnet allowlist.",
            )
        )
        checks.append(
            CheckResult(
                "recipient_shape",
                looks_like_evm_address(plan.recipient),
                "Recipient must be a valid 20-byte EVM address.",
            )
        )
        checks.append(
            CheckResult(
                "recipient_nonzero",
                plan.recipient.lower() != "0x" + "0" * 40,
                "Zero-address transfers are prohibited.",
            )
        )
        checks.append(
            CheckResult(
                "positive_amount",
                plan.amount > 0,
                "Transfer amount must be positive.",
            )
        )
        checks.append(
            CheckResult(
                "amount_cap",
                plan.amount <= self.config.max_native_amount,
                f"Transfer exceeds the MVP cap of {self.config.max_native_amount} native tokens.",
            )
        )
        checks.append(
            CheckResult(
                "native_asset_only",
                plan.asset == "native",
                "The MVP allows the chain-native test token only.",
            )
        )

        if self.config.require_recipient_allowlist:
            allowed = {address.lower() for address in self.config.allowed_recipients}
            checks.append(
                CheckResult(
                    "recipient_allowlist",
                    plan.recipient.lower() in allowed,
                    "Recipient is not in the configured allowlist.",
                )
            )

        if self.config.wallet_address and not self.config.allow_self_transfer:
            checks.append(
                CheckResult(
                    "no_self_transfer",
                    plan.recipient.lower() != self.config.wallet_address.lower(),
                    "Self-transfers are disabled for the product path.",
                )
            )

        return PolicyDecision(passed=all(check.passed for check in checks), checks=tuple(checks))

