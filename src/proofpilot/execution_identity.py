from __future__ import annotations

from typing import Any

from .models import CheckResult, VerificationResult


def select_single_web3_integration(integrations: Any) -> dict[str, Any] | None:
    if not isinstance(integrations, list):
        return None
    rows = [row for row in integrations if isinstance(row, dict) and row.get("type") == "web3"]
    return rows[0] if len(rows) == 1 else None


def verify_supported_eoa_identity(
    integration: dict[str, Any] | None,
    wallet_details: dict[str, Any] | None,
) -> VerificationResult:
    """Allow only the live-tested direct-web3 EOA execution profile.

    Safe/active-Sender semantics are deliberately unsupported until simulation identity can
    be proven equivalent to the actual semantic sender.
    """

    integration = integration or {}
    wallet_details = wallet_details or {}
    integration_address = str(integration.get("address") or integration.get("name") or "")
    wallet_address = str(wallet_details.get("walletAddress") or "")
    config = wallet_details.get("config")
    config_is_empty = config in ({}, None)
    text = repr({"integration": integration, "wallet": wallet_details}).lower()
    safe_markers = any(marker in text for marker in ("safeaddress", "safesender", "multisig"))

    checks = (
        CheckResult(
            "execution_identity_integration_type",
            integration.get("type") == "web3" and wallet_details.get("type") == "web3",
            "Execution identity is not the supported KeeperHub web3 wallet profile.",
        ),
        CheckResult(
            "execution_identity_single_wallet",
            bool(integration),
            "Exactly one KeeperHub web3 integration is required for autonomous execution.",
        ),
        CheckResult(
            "execution_identity_wallet_address",
            bool(integration_address)
            and bool(wallet_address)
            and integration_address.lower() == wallet_address.lower(),
            "KeeperHub integration address and walletAddress differ or are unavailable.",
        ),
        CheckResult(
            "execution_identity_no_safe_sender",
            config_is_empty and not safe_markers,
            "Safe/active-Sender configuration is unsupported by the current verified profile.",
        ),
    )
    return VerificationResult(all(check.passed for check in checks), checks)
