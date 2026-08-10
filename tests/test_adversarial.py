from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.adversarial import GeneratedAttack, generate_contract_trial  # noqa: E402


TARGET = "0x1111111111111111111111111111111111111111"


class AdversarialGeneratorTests(unittest.TestCase):
    def test_trial_is_reproducible_and_has_ten_cases(self) -> None:
        first = generate_contract_trial(trial_id=7, seed=123, target=TARGET)
        second = generate_contract_trial(trial_id=7, seed=123, target=TARGET)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 10)
        self.assertEqual(sum(case.should_approve for case in first), 2)

    def test_stale_case_keeps_safe_proposal_but_changes_snapshot(self) -> None:
        cases = generate_contract_trial(trial_id=0, seed=9, target=TARGET)
        stale = next(case for case in cases if case.attack == GeneratedAttack.STALE_SNAPSHOT)
        safe = next(case for case in cases if case.attack == GeneratedAttack.SAFE_EXACT)
        self.assertEqual(stale.proposal, safe.proposal)
        self.assertNotEqual(stale.expected_snapshot, stale.observed_snapshot)


if __name__ == "__main__":
    unittest.main()
