from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.config import Gate0Config  # noqa: E402


class Gate0ConfigTests(unittest.TestCase):
    def test_rejects_non_base_sepolia(self) -> None:
        config = Gate0Config(
            api_key="kh_test",
            recipient="0x" + "1" * 40,
            amount="0.000001",
            chain_id="1",
        )
        self.assertTrue(any("Base Sepolia" in item for item in config.validate()))

    def test_rejects_amount_above_gate0_cap(self) -> None:
        config = Gate0Config(
            api_key="kh_test",
            recipient="0x" + "1" * 40,
            amount="0.01",
        )
        self.assertTrue(any("safety cap" in item for item in config.validate()))

    def test_env_defaults_to_base_sepolia(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Gate0Config.from_env()
        self.assertEqual(config.chain_id, "84532")


if __name__ == "__main__":
    unittest.main()

