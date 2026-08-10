from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.keeperhub import verify_terminal_success  # noqa: E402


class ReceiptVerificationTests(unittest.TestCase):
    def test_accepts_verified_success_receipt(self) -> None:
        ok, errors = verify_terminal_success(
            {
                "status": "completed",
                "transactionHash": "0xabc",
                "transactionLink": "https://example.test/tx/0xabc",
                "receipts": [{"verified": True, "receiptStatus": "success"}],
            }
        )
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_fails_closed_without_verified_receipt(self) -> None:
        ok, errors = verify_terminal_success(
            {
                "status": "completed",
                "transactionHash": "0xabc",
                "transactionLink": "https://example.test/tx/0xabc",
                "receipts": [{"verified": False, "receiptStatus": "timeout"}],
            }
        )
        self.assertFalse(ok)
        self.assertGreaterEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()

