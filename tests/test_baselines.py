from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.adversarial import generate_repeated_contract_suite  # noqa: E402
from proofpilot.baselines import default_baselines  # noqa: E402
from proofpilot.keeperbench21 import evaluate_cases  # noqa: E402


TARGET = "0x1111111111111111111111111111111111111111"


class BaselineComparisonTests(unittest.TestCase):
    def test_semantic_assurance_beats_execution_and_static_baselines(self) -> None:
        cases = generate_repeated_contract_suite(trials=10, seed=20260808, target=TARGET)
        _, summaries = evaluate_cases(cases, default_baselines())
        by_name = {summary.evaluator: summary for summary in summaries}
        self.assertEqual(by_name["execution_only"].unsafe_approval_rate, 0.875)
        self.assertEqual(by_name["static_allowlist"].unsafe_approval_rate, 0.375)
        self.assertEqual(by_name["proofpilot"].unsafe_approval_rate, 0.0)
        self.assertEqual(by_name["proofpilot"].safe_acceptance_rate, 1.0)


if __name__ == "__main__":
    unittest.main()
