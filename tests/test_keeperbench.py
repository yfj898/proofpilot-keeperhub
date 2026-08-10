from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.keeperbench import (  # noqa: E402
    default_contract_suite,
    default_transfer_suite,
    run_state_semantics_suite,
    run_keeperbench,
)


TARGET = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"


class KeeperBenchTests(unittest.TestCase):
    def test_default_suites_have_zero_unsafe_approvals(self) -> None:
        scenarios = [
            *default_transfer_suite(target=TARGET, wrong_target=OTHER),
            *default_contract_suite(target=TARGET, wrong_target=OTHER),
        ]
        _, summary = run_keeperbench(scenarios)
        self.assertEqual(summary.total, 10)
        self.assertEqual(summary.correct, summary.total)
        self.assertEqual(summary.unsafe_approved, 0)
        self.assertEqual(summary.unsafe_approval_rate, 0.0)
        self.assertEqual(summary.safe_rejection_rate, 0.0)

    def test_state_semantics_suite_detects_stale_and_bad_outcomes(self) -> None:
        results = run_state_semantics_suite()
        self.assertEqual(len(results), 5)
        self.assertTrue(all(result.correct for result in results))


if __name__ == "__main__":
    unittest.main()

