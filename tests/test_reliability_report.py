from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_reliability_report import build_report  # noqa: E402


class ReliabilityReportTests(unittest.TestCase):
    def test_report_is_fail_closed_and_complete(self) -> None:
        report = build_report()
        summary = report["summary"]
        self.assertGreaterEqual(summary["total_cases"], 13)
        self.assertEqual(summary["failed_cases"], 0)
        self.assertEqual(summary["unsafe_broadcasts"], 0)
        ids = {case["case_id"] for case in report["cases"]}
        for required in {
            "wrong_chain",
            "wrong_target",
            "wrong_function",
            "wrong_arguments",
            "wrong_native_value",
            "stale_state",
            "simulation_revert",
            "mcp_tool_error",
            "duplicate_replay",
            "uncertain_execution_status",
            "receipt_failure",
            "postcondition_mismatch",
            "tampered_trace",
        }:
            self.assertIn(required, ids)


if __name__ == "__main__":
    unittest.main()
