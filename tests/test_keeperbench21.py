from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.adversarial import generate_repeated_contract_suite  # noqa: E402
from proofpilot.baselines import default_baselines  # noqa: E402
from proofpilot.keeperbench21 import comparison_artifact, evaluate_cases  # noqa: E402


class KeeperBench21Tests(unittest.TestCase):
    def test_artifact_counts_generated_cases_not_evaluator_rows(self) -> None:
        cases = generate_repeated_contract_suite(
            trials=3,
            seed=1,
            target="0x1111111111111111111111111111111111111111",
        )
        rows, summaries = evaluate_cases(cases, default_baselines())
        artifact = comparison_artifact(
            trials=3,
            seed=1,
            target="0x1111111111111111111111111111111111111111",
            rows=rows,
            summaries=summaries,
        )
        self.assertEqual(artifact["generated_cases"], 30)
        self.assertEqual(len(artifact["evaluators"]), 3)
        self.assertEqual(
            artifact["attack_breakdown"]["proofpilot"]["wrong_argument_scale"]["approval_rate"],
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
