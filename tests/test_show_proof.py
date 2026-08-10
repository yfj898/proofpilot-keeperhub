from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from proofpilot.proof_bundle import build_execution_trace_v2  # noqa: E402
from show_proof import render_trace  # noqa: E402


class ShowProofTests(unittest.TestCase):
    def test_renders_verified_trace(self) -> None:
        trace = build_execution_trace_v2(
            user_intent="Set Aave E-Mode to 1",
            intent_ir={"action": {"function_signature": "setUserEMode(uint8)", "arguments": [1]}},
            intent_commitment="a" * 64,
            proposal={
                "target": "0x" + "1" * 40,
                "function_signature": "setUserEMode(uint8)",
                "arguments": [1],
                "native_value": "0",
            },
            intent_assurance={"passed": True, "checks": []},
            pre_state={"aave": {"user_emode": 0}},
            keeperhub_simulation={"success": True, "wouldRevert": False},
            keeperhub_execution={
                "execution_id": "exec-1",
                "status": "completed",
                "transaction_hash": "0xabc",
                "terminal_check": {"passed": True},
            },
            independent_receipt={"passed": True},
            post_state={"aave": {"user_emode": 1}},
            postcondition_check={"passed": True},
            final_status="VERIFIED",
            broadcast_attempted=True,
        )
        rendered = render_trace(trace)
        self.assertIn("Status: VERIFIED", rendered)
        self.assertIn("Transaction: 0xabc", rendered)
        self.assertIn("Trace integrity: PASS", rendered)

    def test_renders_blocked_semantic_deviation(self) -> None:
        trace = build_execution_trace_v2(
            user_intent="Set Aave E-Mode to 1",
            intent_ir={},
            intent_commitment="a" * 64,
            proposal={
                "target": "0x" + "1" * 40,
                "function_signature": "setUserEMode(uint8)",
                "arguments": [0],
                "native_value": "0",
            },
            intent_assurance={"passed": False, "checks": []},
            pre_state={"aave": {"user_emode": 0}},
            keeperhub_simulation={"success": True, "wouldRevert": False},
            semantic_deviations=["wrong_emode_category"],
            final_status="BLOCKED",
            broadcast_attempted=False,
        )
        rendered = render_trace(trace)
        self.assertIn("wrong_emode_category", rendered)
        self.assertIn("Status: BLOCKED", rendered)
        self.assertIn("Broadcast attempted: False", rendered)


if __name__ == "__main__":
    unittest.main()
