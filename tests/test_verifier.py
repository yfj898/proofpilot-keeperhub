from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.intent import IntentAction, ProposedAction  # noqa: E402
from proofpilot.models import ActionKind, ExecutionPlan  # noqa: E402
from proofpilot.verifier import (  # noqa: E402
    AAVE_USER_EMODE_SET_TOPIC0,
    verify_aave_emode_execution_binding,
    verify_independent_receipt,
    verify_simulation,
    verify_simulation_binding,
    verify_terminal_execution,
    verify_transfer_postcondition,
)


class VerifierTests(unittest.TestCase):
    def test_simulation_passes_only_on_explicit_non_revert(self) -> None:
        result = verify_simulation(
            {"success": True, "status": "simulated", "wouldRevert": False}
        )
        self.assertTrue(result.passed)

    def test_simulation_fails_closed_when_field_missing(self) -> None:
        result = verify_simulation({"success": True, "status": "simulated"})
        self.assertFalse(result.passed)

    def test_terminal_execution_requires_verified_receipt(self) -> None:
        result = verify_terminal_execution(
            {
                "status": "completed",
                "transactionHash": "0xabc",
                "transactionLink": "https://example.test/0xabc",
                "receipts": [{"verified": True, "receiptStatus": "success"}],
            }
        )
        self.assertTrue(result.passed, result.reasons)

    def test_postcondition_checks_balance_delta(self) -> None:
        plan = ExecutionPlan(
            ActionKind.TRANSFER_NATIVE,
            "84532",
            "0x1111111111111111111111111111111111111111",
            Decimal("0.001"),
        )
        result = verify_transfer_postcondition(
            plan,
            recipient_balance_before="1.0",
            recipient_balance_after="1.001",
        )
        self.assertTrue(result.passed, result.reasons)

    def test_postcondition_rejects_short_delta(self) -> None:
        plan = ExecutionPlan(
            ActionKind.TRANSFER_NATIVE,
            "84532",
            "0x1111111111111111111111111111111111111111",
            Decimal("0.001"),
        )
        result = verify_transfer_postcondition(
            plan,
            recipient_balance_before="1.0",
            recipient_balance_after="1.0001",
        )
        self.assertFalse(result.passed)

    def test_independent_receipt_requires_hash_status_and_block(self) -> None:
        result = verify_independent_receipt(
            "0xabc",
            {
                "transactionHash": "0xabc",
                "status": "0x1",
                "blockHash": "0xdef",
                "blockNumber": "0x1",
            },
        )
        self.assertTrue(result.passed, result.reasons)

    def test_independent_receipt_rejects_failed_status(self) -> None:
        result = verify_independent_receipt(
            "0xabc",
            {
                "transactionHash": "0xabc",
                "status": "0x0",
                "blockHash": "0xdef",
                "blockNumber": "0x1",
            },
        )
        self.assertFalse(result.passed)

    def test_terminal_execution_accepts_documented_status_without_enriched_receipts(self) -> None:
        result = verify_terminal_execution(
            {
                "status": "completed",
                "transactionHash": "0xabc",
                "transactionLink": "https://example.test/0xabc",
            }
        )
        self.assertTrue(result.passed, result.reasons)

    def test_simulation_binding_requires_target_value_and_sender(self) -> None:
        proposal = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id="84532",
            target="0x1111111111111111111111111111111111111111",
            function_signature="setUserEMode(uint8)",
            arguments=(1,),
            native_value=Decimal("0"),
        )
        result = verify_simulation_binding(
            {
                "to": proposal.target,
                "from": "0x2222222222222222222222222222222222222222",
                "value": "0",
            },
            proposal,
            expected_sender="0x2222222222222222222222222222222222222222",
        )
        self.assertTrue(result.passed, result.reasons)

    def test_aave_execution_binding_uses_envelope_identity_and_event(self) -> None:
        account = "0x4c3bfdf14c3e60ff736df20f13b40923bf1cbab5"
        pool = "0x8bab6d1b75f19e9ed9fce8b9bd338844ff79ae27"
        tx = {
            "value": "0x0",
            "input": "0xdeadbeef"
            + account[2:].rjust(64, "0")
            + pool[2:].rjust(64, "0"),
        }
        receipt = {
            "logs": [
                {
                    "address": pool,
                    "topics": [
                        AAVE_USER_EMODE_SET_TOPIC0,
                        "0x" + account[2:].rjust(64, "0"),
                    ],
                    "data": "0x" + hex(1)[2:].rjust(64, "0"),
                }
            ]
        }
        result = verify_aave_emode_execution_binding(
            transaction=tx,
            receipt=receipt,
            pool=pool,
            account=account,
            category_id=1,
            simulated_sender=account,
        )
        self.assertTrue(result.passed, result.reasons)


if __name__ == "__main__":
    unittest.main()

