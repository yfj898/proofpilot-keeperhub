from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.aave_adapter import AaveEthSupplyAdapter  # noqa: E402
from proofpilot.erc20_adapter import ERC20TransferAdapter  # noqa: E402


ADDRESS = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"


class ProtocolAdapterTests(unittest.TestCase):
    def test_erc20_outcome_requires_two_balance_deltas(self) -> None:
        adapter = ERC20TransferAdapter(ADDRESS, ADDRESS, OTHER, 25)
        mandate = adapter.mandate(intent_id="erc20")
        self.assertTrue(adapter.verify_outcome(mandate, {"sender": 100, "recipient": 5}, {"sender": 75, "recipient": 30}).passed)
        self.assertFalse(adapter.verify_outcome(mandate, {"sender": 100, "recipient": 5}, {"sender": 75, "recipient": 29}).passed)

    def test_aave_outcome_requires_atoken_increase_and_no_new_debt(self) -> None:
        adapter = AaveEthSupplyAdapter(ADDRESS, Decimal("0.000001"))
        mandate = adapter.mandate(intent_id="aave")
        amount_wei = 10**12
        good = adapter.verify_outcome(
            mandate,
            {"a_weth": 100, "variable_debt": 0},
            {"a_weth": 100 + amount_wei, "variable_debt": 0},
        )
        self.assertTrue(good.passed)
        self.assertFalse(
            adapter.verify_outcome(
                mandate,
                {"a_weth": 100, "variable_debt": 0},
                {"a_weth": 100 + amount_wei, "variable_debt": 1},
            ).passed
        )


if __name__ == "__main__":
    unittest.main()

