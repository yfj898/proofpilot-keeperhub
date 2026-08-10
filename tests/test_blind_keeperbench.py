from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.blind_keeperbench import build_blind_artifact  # noqa: E402


TARGET = "0x893a327e3714b2780B28C35FfEcb52AfA0157F15"


class BlindKeeperBenchTests(unittest.TestCase):
    def test_attacker_is_source_separated_and_heldout_cases_are_contained(self) -> None:
        artifact = build_blind_artifact(ROOT, target=TARGET, seed=20260808, trials=3)
        self.assertFalse(artifact["attacker_imports_defender"])
        self.assertEqual(artifact["generated_cases"], 21)
        by_name = {row["evaluator"]: row for row in artifact["evaluators"]}
        self.assertGreater(by_name["execution_only"]["unsafe_approval_rate"], 0)
        self.assertGreater(by_name["static_allowlist"]["unsafe_approval_rate"], 0)
        self.assertEqual(by_name["proofpilot"]["unsafe_approval_rate"], 0)
        self.assertEqual(len(artifact["cases_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()

