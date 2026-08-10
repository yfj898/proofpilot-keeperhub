from __future__ import annotations

import os
from dataclasses import dataclass


BASE_SEPOLIA_CHAIN_ID = "84532"
KEEPERHUB_MCP_URL = "https://app.keeperhub.com/mcp"


@dataclass(frozen=True)
class Gate0Config:
    api_key: str
    recipient: str
    amount: str
    chain_id: str = BASE_SEPOLIA_CHAIN_ID
    endpoint: str = KEEPERHUB_MCP_URL

    @classmethod
    def from_env(cls) -> "Gate0Config":
        return cls(
            api_key=os.getenv("KH_API_KEY", "").strip(),
            recipient=os.getenv("PROOFPILOT_RECIPIENT", "").strip(),
            amount=os.getenv("PROOFPILOT_AMOUNT", "0.000001").strip(),
            chain_id=os.getenv("PROOFPILOT_CHAIN_ID", BASE_SEPOLIA_CHAIN_ID).strip(),
            endpoint=os.getenv("KEEPERHUB_MCP_URL", KEEPERHUB_MCP_URL).strip(),
        )

    def validate(self, *, require_credentials: bool = True) -> list[str]:
        errors: list[str] = []
        if self.chain_id != BASE_SEPOLIA_CHAIN_ID:
            errors.append(
                f"Gate 0 is testnet-only: expected Base Sepolia chain_id={BASE_SEPOLIA_CHAIN_ID}."
            )
        if require_credentials and not self.api_key:
            errors.append("KH_API_KEY is not set.")
        if require_credentials and self.api_key and not self.api_key.startswith("kh_"):
            errors.append("KH_API_KEY must be an organisation key with the kh_ prefix.")
        if require_credentials and not _looks_like_evm_address(self.recipient):
            errors.append("PROOFPILOT_RECIPIENT must be a 20-byte EVM address (0x + 40 hex chars).")
        if require_credentials and self.recipient.lower() == "0x" + "0" * 40:
            errors.append("PROOFPILOT_RECIPIENT is still the zero-address placeholder.")
        try:
            value = float(self.amount)
            if value <= 0:
                errors.append("PROOFPILOT_AMOUNT must be positive.")
            if value > 0.001:
                errors.append("Gate 0 safety cap: PROOFPILOT_AMOUNT must be <= 0.001 testnet ETH.")
        except ValueError:
            errors.append("PROOFPILOT_AMOUNT must be a decimal number string.")
        return errors


def _looks_like_evm_address(value: str) -> bool:
    if len(value) != 42 or not value.startswith("0x"):
        return False
    try:
        int(value[2:], 16)
    except ValueError:
        return False
    return True

