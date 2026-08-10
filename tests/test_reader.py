from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.reader import BaseSepoliaReader  # noqa: E402


class FakeReader(BaseSepoliaReader):
    def __init__(self, responses: dict[str, object]):
        self.responses = responses

    def _rpc(self, method: str, params: list[object]) -> object:
        return self.responses[method]


class ReaderTests(unittest.TestCase):
    def test_reads_balance_in_eth_units(self) -> None:
        reader = FakeReader({"eth_getBalance": hex(10**15)})
        balance = reader.get_native_balance("0x1111111111111111111111111111111111111111")
        self.assertEqual(str(balance), "0.001")

    def test_reads_chain_id(self) -> None:
        reader = FakeReader({"eth_chainId": hex(84532)})
        self.assertEqual(reader.chain_id(), "84532")

    def test_reads_receipt(self) -> None:
        receipt = {"transactionHash": "0xabc", "status": "0x1"}
        reader = FakeReader({"eth_getTransactionReceipt": receipt})
        self.assertEqual(reader.get_transaction_receipt("0xabc"), receipt)

    def test_reads_raw_transaction(self) -> None:
        transaction = {"hash": "0xabc", "to": "0x" + "1" * 40, "input": "0x1234"}
        reader = FakeReader({"eth_getTransactionByHash": transaction})
        self.assertEqual(reader.get_transaction("0xabc"), transaction)

    def test_reads_uint_and_bool_with_eth_call(self) -> None:
        reader = FakeReader({"eth_call": "0x14"})
        self.assertEqual(reader.read_uint256("0x" + "1" * 40, "0x12345678"), 20)
        reader = FakeReader({"eth_call": "0x0"})
        self.assertFalse(reader.read_bool("0x" + "1" * 40, "0x87654321"))

    def test_reads_raw_storage_uint256(self) -> None:
        reader = FakeReader({"eth_getStorageAt": "0x14"})
        self.assertEqual(reader.get_storage_uint256("0x" + "1" * 40, 0), 20)

    def test_reads_aave_user_emode(self) -> None:
        account = "0x" + "2" * 40
        pool = "0x" + "3" * 40
        reader = FakeReader({"eth_call": "0x1"})
        self.assertEqual(reader.aave_user_emode(pool, account), 1)


if __name__ == "__main__":
    unittest.main()

