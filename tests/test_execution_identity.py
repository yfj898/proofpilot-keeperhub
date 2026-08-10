from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.execution_identity import (  # noqa: E402
    select_single_web3_integration,
    verify_supported_eoa_identity,
)


ADDRESS = "0x" + "1" * 40


class ExecutionIdentityTests(unittest.TestCase):
    def test_current_direct_web3_eoa_profile_passes(self) -> None:
        integration = {"id": "wallet-1", "type": "web3", "address": ADDRESS}
        wallet = {"id": "wallet-1", "type": "web3", "config": {}, "walletAddress": ADDRESS}
        self.assertTrue(verify_supported_eoa_identity(integration, wallet).passed)

    def test_safe_sender_configuration_fails_closed(self) -> None:
        integration = {"id": "wallet-1", "type": "web3", "address": ADDRESS}
        wallet = {
            "id": "wallet-1",
            "type": "web3",
            "walletAddress": ADDRESS,
            "config": {"safeAddress": "0x" + "2" * 40},
        }
        self.assertFalse(verify_supported_eoa_identity(integration, wallet).passed)

    def test_multiple_web3_integrations_are_ambiguous(self) -> None:
        integrations = [
            {"id": "a", "type": "web3", "address": ADDRESS},
            {"id": "b", "type": "web3", "address": "0x" + "2" * 40},
        ]
        self.assertIsNone(select_single_web3_integration(integrations))


if __name__ == "__main__":
    unittest.main()
