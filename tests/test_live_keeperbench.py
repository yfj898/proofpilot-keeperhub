from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.live_keeperbench import LiveBenchResult, summarize_live_results  # noqa: E402


class LiveKeeperBenchSummaryTests(unittest.TestCase):
    def test_metrics_count_prewrite_escape_and_tamper_detection(self) -> None:
        results = [
            LiveBenchResult("bad-args", "semantic_prewrite", "block", True),
            LiveBenchResult("race", "freshness_prewrite", "block", True, adversary_write_calls=1),
            LiveBenchResult("replay", "semantic_replay", "block", True),
            LiveBenchResult("tamper", "evidence_tamper", "detect", True),
            LiveBenchResult("recover", "semantic_recovery", "recover", True, primary_write_calls=1),
        ]
        summary = summarize_live_results(results)
        self.assertEqual(summary.total, 5)
        self.assertEqual(summary.unsafe_approval_rate, 0.0)
        self.assertEqual(summary.prewrite_containment_rate, 1.0)
        self.assertEqual(summary.evidence_tamper_detection_rate, 1.0)
        self.assertEqual(summary.recovery_success_rate, 1.0)


if __name__ == "__main__":
    unittest.main()
