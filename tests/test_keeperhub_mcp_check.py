from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from keeperhub_mcp_check import (  # noqa: E402
    REQUIRED_AGENT_NATIVE_TOOLS,
    _contains_evm_address,
    build_report,
)
from proofpilot.config import KEEPERHUB_MCP_URL  # noqa: E402


class _Initialized:
    status = 200


class FakeClient:
    protocol_version = "2025-11-25"

    def initialize(self):
        return _Initialized()

    def list_tools(self):
        return [{"name": name} for name in REQUIRED_AGENT_NATIVE_TOOLS] + [
            {"name": "execute_transfer"}
        ]

    def call_tool(self, name, arguments):
        self.last_call = (name, arguments)
        return {"wallet": {"address": "0x" + "1" * 40}}


class KeeperHubMcpCheckTests(unittest.TestCase):
    def test_detects_nested_evm_address(self) -> None:
        self.assertTrue(_contains_evm_address({"x": [{"address": "0x" + "a" * 40}]}))
        self.assertFalse(_contains_evm_address({"x": ["not-an-address"]}))

    def test_report_is_read_only_and_requires_agent_native_tools(self) -> None:
        client = FakeClient()
        report = build_report(client=client, endpoint=KEEPERHUB_MCP_URL)
        self.assertTrue(report["official_hosted_endpoint"])
        self.assertTrue(report["all_required_tools_present"])
        self.assertTrue(report["wallet_integration_address_present"])
        self.assertFalse(report["write_performed"])
        self.assertEqual(client.last_call, ("list_integrations", {}))


if __name__ == "__main__":
    unittest.main()
