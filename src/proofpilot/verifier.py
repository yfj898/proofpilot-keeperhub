from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .intent import ProposedAction
from .models import CheckResult, ExecutionPlan, VerificationResult


AAVE_USER_EMODE_SET_TOPIC0 = (
    "0xd728da875fc88944cbf17638bcbe4af0eedaef63becd1d1c57cc097eb4608d84"
)


def verify_simulation(simulation: dict[str, Any]) -> VerificationResult:
    checks = (
        CheckResult(
            "simulation_success",
            simulation.get("success") is True,
            "Simulation did not return success=true.",
        ),
        CheckResult(
            "simulation_non_reverting",
            simulation.get("wouldRevert") is False,
            "Simulation indicates the transaction would revert.",
        ),
        CheckResult(
            "simulation_status",
            str(simulation.get("status", "")).lower() == "simulated",
            "Simulation response does not report status=simulated.",
        ),
    )
    return VerificationResult(all(check.passed for check in checks), checks)


def verify_simulation_binding(
    simulation: dict[str, Any],
    proposal: ProposedAction,
    *,
    expected_sender: str | None = None,
) -> VerificationResult:
    """Bind simulation evidence to the exact authorized target/value and execution identity."""

    observed_to = str(simulation.get("to", ""))
    observed_from = str(simulation.get("from", ""))
    observed_value = simulation.get("value")
    expected_wei = proposal.native_value * (Decimal(10) ** 18)
    expected_wei_int = int(expected_wei) if expected_wei == expected_wei.to_integral_value() else -1
    try:
        observed_wei = int(str(observed_value), 0) if isinstance(observed_value, str) else int(observed_value)
    except (TypeError, ValueError):
        observed_wei = -2

    checks: list[CheckResult] = [
        CheckResult(
            "simulation_target_binding",
            observed_to.lower() == proposal.target.lower(),
            "KeeperHub simulation target does not match the authorized proposal target.",
        ),
        CheckResult(
            "simulation_value_binding",
            observed_wei == expected_wei_int,
            "KeeperHub simulation native value does not match the authorized proposal.",
        ),
    ]
    if expected_sender is not None:
        checks.append(
            CheckResult(
                "simulation_sender_binding",
                observed_from.lower() == expected_sender.lower(),
                "KeeperHub simulation sender does not match the expected execution identity.",
            )
        )
    return VerificationResult(all(check.passed for check in checks), tuple(checks))


def verify_aave_emode_execution_binding(
    *,
    transaction: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
    pool: str,
    account: str,
    category_id: int,
    simulated_sender: str,
) -> VerificationResult:
    """Bind a KeeperHub-routed transaction to the authorized Aave E-Mode effect.

    KeeperHub may route writes through an execution contract, so the outer transaction
    `to` is not necessarily the Aave Pool. We verify that the execution envelope contains
    the expected account and Pool target, and that the Pool emitted the canonical
    UserEModeSet(user, categoryId) event for that same identity/category.

    This is an effect/identity binding rather than a full EVM call-trace proof.
    """

    tx_input = str((transaction or {}).get("input", ""))
    tx_value = str((transaction or {}).get("value", ""))
    padded_account = account[2:].lower().rjust(64, "0")
    padded_pool = pool[2:].lower().rjust(64, "0")
    checks: list[CheckResult] = [
        CheckResult(
            "execution_transaction_present",
            isinstance(transaction, dict),
            "Independent read layer could not fetch the broadcast transaction.",
        ),
        CheckResult(
            "execution_envelope_account_binding",
            padded_account in tx_input.lower(),
            "KeeperHub execution envelope does not contain the expected execution account.",
        ),
        CheckResult(
            "execution_envelope_target_binding",
            padded_pool in tx_input.lower(),
            "KeeperHub execution envelope does not contain the authorized Aave Pool target.",
        ),
        CheckResult(
            "execution_outer_native_value",
            tx_value in {"0x0", "0x00", "0"},
            "Outer KeeperHub execution transaction unexpectedly carries native value.",
        ),
        CheckResult(
            "execution_identity_matches_simulation",
            simulated_sender.lower() == account.lower(),
            "Simulation sender and intended execution account differ.",
        ),
    ]

    matching_event = False
    if isinstance(receipt, dict):
        for log in receipt.get("logs") or []:
            if not isinstance(log, dict) or str(log.get("address", "")).lower() != pool.lower():
                continue
            topics = log.get("topics") or []
            if not isinstance(topics, list) or len(topics) < 2:
                continue
            try:
                event_category = int(str(log.get("data", "0x0")), 16)
            except ValueError:
                continue
            if (
                str(topics[0]).lower() == AAVE_USER_EMODE_SET_TOPIC0
                and str(topics[1]).lower().endswith(account[2:].lower())
                and event_category == category_id
            ):
                matching_event = True
                break
    checks.append(
        CheckResult(
            "aave_user_emode_event_binding",
            matching_event,
            "Aave Pool did not emit UserEModeSet for the expected user/category.",
        )
    )
    return VerificationResult(all(check.passed for check in checks), tuple(checks))


def verify_terminal_execution(status: dict[str, Any]) -> VerificationResult:
    checks: list[CheckResult] = [
        CheckResult(
            "execution_completed",
            str(status.get("status", "")).lower() == "completed",
            "Execution status is not completed.",
        ),
        CheckResult(
            "transaction_hash",
            bool(status.get("transactionHash") or status.get("transaction_hash")),
            "Transaction hash is missing.",
        ),
        CheckResult(
            "transaction_link",
            bool(status.get("transactionLink") or status.get("transaction_link")),
            "Transaction link is missing.",
        ),
    ]

    receipts = status.get("receipts")
    if isinstance(receipts, list) and receipts:
        checks.append(CheckResult("receipt_evidence", True, "Enriched receipt evidence is present."))
        for index, receipt in enumerate(receipts):
            if not isinstance(receipt, dict):
                checks.append(
                    CheckResult(f"receipt_{index}_shape", False, "Receipt has invalid shape.")
                )
                continue
            checks.append(
                CheckResult(
                    f"receipt_{index}_verified",
                    receipt.get("verified") is True,
                    "Receipt is not cryptographically/chain verified by the execution layer.",
                )
            )
            checks.append(
                CheckResult(
                    f"receipt_{index}_status",
                    receipt.get("receiptStatus") == "success",
                    f"receiptStatus={receipt.get('receiptStatus')!r}; expected 'success'.",
                )
            )
    else:
        checks.append(
            CheckResult(
                "receipt_evidence_optional",
                True,
                "KeeperHub status omitted enriched receipts; independent RPC verification remains required.",
            )
        )

    return VerificationResult(all(check.passed for check in checks), tuple(checks))


def verify_transfer_postcondition(
    plan: ExecutionPlan,
    *,
    recipient_balance_before: str | Decimal,
    recipient_balance_after: str | Decimal,
    tolerance: Decimal = Decimal("0"),
) -> VerificationResult:
    """Verify a recipient-balance postcondition from an independent read layer.

    For a normal transfer, the recipient balance should increase by at least the
    planned amount minus an explicitly configured tolerance.  This verifier should
    not be used for self-transfers because gas makes balance deltas non-monotonic.
    """

    try:
        before = Decimal(str(recipient_balance_before))
        after = Decimal(str(recipient_balance_after))
    except (InvalidOperation, ValueError):
        return VerificationResult(
            False,
            (CheckResult("post_balance_parse", False, "Balance observation is not a decimal value."),),
        )

    delta = after - before
    required = plan.amount - tolerance
    checks = (
        CheckResult(
            "post_balance_nonnegative_delta",
            delta >= 0,
            f"Recipient balance decreased by {-delta}.",
        ),
        CheckResult(
            "post_balance_amount",
            delta >= required,
            f"Recipient balance delta {delta} is below required {required}.",
        ),
    )
    return VerificationResult(all(check.passed for check in checks), checks)


def verify_independent_receipt(
    tx_hash: str,
    receipt: dict[str, Any] | None,
) -> VerificationResult:
    """Cross-check KeeperHub tx evidence against an independent Base RPC receipt."""

    if receipt is None:
        return VerificationResult(
            False,
            (
                CheckResult(
                    "independent_receipt_present",
                    False,
                    "Transaction receipt is not visible on the independent read layer yet.",
                ),
            ),
        )

    observed_hash = receipt.get("transactionHash")
    status = receipt.get("status")
    checks = (
        CheckResult(
            "independent_receipt_hash",
            isinstance(observed_hash, str) and observed_hash.lower() == tx_hash.lower(),
            "Independent receipt transactionHash does not match KeeperHub evidence.",
        ),
        CheckResult(
            "independent_receipt_success",
            status in {"0x1", 1, "1"},
            f"Independent receipt status={status!r}; expected successful EVM status.",
        ),
        CheckResult(
            "independent_receipt_block",
            bool(receipt.get("blockHash") and receipt.get("blockNumber")),
            "Independent receipt is missing block inclusion evidence.",
        ),
    )
    return VerificationResult(all(check.passed for check in checks), checks)

