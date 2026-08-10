from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.keeperhub import KeeperHubGate0  # noqa: E402
from proofpilot.mcp import McpError  # noqa: E402


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def call_tool(self, name, arguments):
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class KeeperHubPollingTests(unittest.TestCase):
    def test_uses_bounded_exponential_backoff(self) -> None:
        sleeps: list[float] = []
        gate = KeeperHubGate0(
            FakeClient(
                [
                    {"status": "pending"},
                    {"status": "pending"},
                    {"status": "completed", "transactionHash": "0x1"},
                ]
            )
        )
        result = gate.poll_status(
            "exec", max_attempts=3, delay_seconds=1, max_delay_seconds=5, sleep_fn=sleeps.append
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_structured_poll_hint_is_honored_and_bounded(self) -> None:
        sleeps: list[float] = []
        gate = KeeperHubGate0(
            FakeClient(
                [
                    {"status": "pending", "pollIntervalHint": 20},
                    {"status": "completed", "transactionHash": "0x1"},
                ]
            )
        )
        gate.poll_status(
            "exec", max_attempts=2, delay_seconds=1, max_delay_seconds=5, sleep_fn=sleeps.append
        )
        self.assertEqual(sleeps, [5])

    def test_http_429_uses_retry_after_without_rebroadcast(self) -> None:
        sleeps: list[float] = []
        gate = KeeperHubGate0(
            FakeClient(
                [
                    McpError("rate limited", status=429, headers={"retry-after": "4"}),
                    {"status": "completed", "transactionHash": "0x1"},
                ]
            )
        )
        result = gate.poll_status(
            "exec", max_attempts=2, delay_seconds=1, max_delay_seconds=5, sleep_fn=sleeps.append
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(sleeps, [4.0])


if __name__ == "__main__":
    unittest.main()
