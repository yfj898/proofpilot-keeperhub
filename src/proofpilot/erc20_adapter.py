from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .intent import IntentAction, IntentMandate, ProposedAction
from .models import CheckResult, VerificationResult
from .reader import BaseSepoliaReader


ERC20_TRANSFER_ABI = (
    '[{"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],'
    '"name":"transfer","outputs":[{"name":"","type":"bool"}],'
    '"stateMutability":"nonpayable","type":"function"}]'
)


@dataclass(frozen=True)
class ERC20TransferAdapter:
    token: str
    sender: str
    recipient: str
    raw_amount: int
    name: str = "erc20_transfer"

    def mandate(self, *, intent_id: str) -> IntentMandate:
        return IntentMandate(
            intent_id=intent_id,
            action=IntentAction.CONTRACT_CALL,
            target=self.token,
            function_signature="transfer(address,uint256)",
            exact_arguments=(self.recipient, self.raw_amount),
            exact_native_value=Decimal("0"),
            description="Transfer the exact ERC-20 amount to the exact recipient.",
        )

    def proposal(self, mandate: IntentMandate) -> ProposedAction:
        return ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id=mandate.chain_id,
            target=self.token,
            function_signature=mandate.function_signature,
            arguments=(self.recipient, self.raw_amount),
        )

    def read_state(self, reader: BaseSepoliaReader, account: str = "") -> dict[str, Any]:
        return {
            "sender": reader.erc20_balance_of(self.token, self.sender),
            "recipient": reader.erc20_balance_of(self.token, self.recipient),
        }

    def verify_outcome(
        self,
        mandate: IntentMandate,
        pre: dict[str, Any],
        post: dict[str, Any],
    ) -> VerificationResult:
        recipient_delta = int(post["recipient"]) - int(pre["recipient"])
        sender_delta = int(pre["sender"]) - int(post["sender"])
        checks = (
            CheckResult(
                "erc20_recipient_delta",
                recipient_delta == self.raw_amount,
                f"Recipient delta={recipient_delta}; expected {self.raw_amount}.",
            ),
            CheckResult(
                "erc20_sender_delta",
                sender_delta == self.raw_amount,
                f"Sender delta={sender_delta}; expected {self.raw_amount}.",
            ),
        )
        return VerificationResult(all(check.passed for check in checks), checks)

