from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from .config import BASE_SEPOLIA_CHAIN_ID
from .models import CheckResult, VerificationResult
from .policy import looks_like_evm_address


class IntentAction(str, Enum):
    TRANSFER_NATIVE = "transfer_native"
    CONTRACT_CALL = "contract_call"


@dataclass(frozen=True)
class ProposedAction:
    action: IntentAction
    chain_id: str
    target: str
    amount: Decimal | None = None
    function_signature: str = ""
    arguments: tuple[Any, ...] = ()
    native_value: Decimal = Decimal("0")
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StateCondition:
    key: str
    operator: str
    expected: Any


@dataclass(frozen=True)
class IntentMandate:
    """Model-independent description of an allowed onchain outcome."""

    intent_id: str
    chain_id: str = BASE_SEPOLIA_CHAIN_ID
    action: IntentAction = IntentAction.TRANSFER_NATIVE
    target: str = ""
    exact_amount: Decimal | None = None
    max_amount: Decimal | None = None
    function_signature: str = ""
    exact_arguments: tuple[Any, ...] | None = None
    exact_native_value: Decimal | None = None
    preconditions: tuple[StateCondition, ...] = ()
    postconditions: tuple[StateCondition, ...] = ()
    forbidden_effects: tuple[str, ...] = ()
    description: str = ""


def assure_intent(mandate: IntentMandate, proposal: ProposedAction) -> VerificationResult:
    checks: list[CheckResult] = [
        CheckResult(
            "intent_chain",
            proposal.chain_id == mandate.chain_id,
            f"Proposal chain_id={proposal.chain_id} does not match mandate chain_id={mandate.chain_id}.",
        ),
        CheckResult(
            "intent_action",
            proposal.action == mandate.action,
            f"Proposal action={proposal.action.value} does not match mandate action={mandate.action.value}.",
        ),
        CheckResult(
            "intent_target_shape",
            looks_like_evm_address(proposal.target),
            "Proposal target must be a valid 20-byte EVM address.",
        ),
        CheckResult(
            "intent_target",
            proposal.target.lower() == mandate.target.lower(),
            "Proposal target differs from the mandated recipient/contract.",
        ),
    ]

    if mandate.action == IntentAction.TRANSFER_NATIVE:
        checks.extend(_check_transfer_amount(mandate, proposal))
    elif mandate.action == IntentAction.CONTRACT_CALL:
        checks.extend(_check_contract_call(mandate, proposal))

    return VerificationResult(all(check.passed for check in checks), tuple(checks))


def verify_state_conditions(
    conditions: tuple[StateCondition, ...],
    state: dict[str, Any],
    *,
    phase: str,
) -> VerificationResult:
    checks: list[CheckResult] = []
    for index, condition in enumerate(conditions):
        observed = _resolve_path(state, condition.key)
        passed = _compare(observed, condition.operator, condition.expected)
        checks.append(
            CheckResult(
                f"{phase}_{index}_{condition.key}",
                passed,
                (
                    f"{phase} condition failed: {condition.key} "
                    f"{condition.operator} {condition.expected!r}; observed={observed!r}."
                ),
            )
        )
    return VerificationResult(all(check.passed for check in checks), tuple(checks))


def verify_state_snapshot_fresh(
    expected_snapshot: dict[str, Any],
    observed_snapshot: dict[str, Any],
    *,
    phase: str = "fresh",
) -> VerificationResult:
    """Fail closed when a previously observed state snapshot has drifted."""

    checks: list[CheckResult] = []
    for path, expected in _flatten_state(expected_snapshot):
        observed = _resolve_path(observed_snapshot, path)
        checks.append(
            CheckResult(
                f"{phase}_{path}",
                observed == expected,
                (
                    f"State snapshot drifted at {path}: "
                    f"expected={expected!r}; observed={observed!r}."
                ),
            )
        )
    if not checks:
        checks.append(
            CheckResult(
                f"{phase}_nonempty",
                False,
                "Freshness check requires a non-empty expected state snapshot.",
            )
        )
    return VerificationResult(all(check.passed for check in checks), tuple(checks))


def _check_transfer_amount(
    mandate: IntentMandate,
    proposal: ProposedAction,
) -> list[CheckResult]:
    amount = proposal.amount
    checks = [
        CheckResult(
            "intent_transfer_amount_present",
            amount is not None,
            "Native transfer proposal is missing an amount.",
        )
    ]
    if amount is None:
        return checks
    checks.append(
        CheckResult(
            "intent_transfer_amount_positive",
            amount.is_finite() and amount > 0,
            "Native transfer amount must be positive and finite.",
        )
    )
    if mandate.exact_amount is not None:
        checks.append(
            CheckResult(
                "intent_exact_amount",
                amount == mandate.exact_amount,
                f"Proposal amount {amount} does not equal mandated amount {mandate.exact_amount}.",
            )
        )
    if mandate.max_amount is not None:
        checks.append(
            CheckResult(
                "intent_max_amount",
                amount <= mandate.max_amount,
                f"Proposal amount {amount} exceeds mandated max {mandate.max_amount}.",
            )
        )
    return checks


def _check_contract_call(
    mandate: IntentMandate,
    proposal: ProposedAction,
) -> list[CheckResult]:
    checks = [
        CheckResult(
            "intent_function",
            proposal.function_signature == mandate.function_signature,
            (
                f"Proposal function {proposal.function_signature!r} does not match "
                f"mandated function {mandate.function_signature!r}."
            ),
        ),
        CheckResult(
            "intent_native_value_valid",
            proposal.native_value.is_finite() and proposal.native_value >= 0,
            "Contract-call native value must be finite and non-negative.",
        ),
    ]
    if mandate.exact_arguments is not None:
        checks.append(
            CheckResult(
                "intent_arguments",
                proposal.arguments == mandate.exact_arguments,
                (
                    f"Proposal arguments {proposal.arguments!r} do not match "
                    f"mandated arguments {mandate.exact_arguments!r}."
                ),
            )
        )
    if mandate.exact_native_value is not None:
        checks.append(
            CheckResult(
                "intent_native_value",
                proposal.native_value == mandate.exact_native_value,
                (
                    f"Proposal native value {proposal.native_value} does not match "
                    f"mandated native value {mandate.exact_native_value}."
                ),
            )
        )
    if mandate.forbidden_effects:
        observed_effects = infer_contract_effects(proposal.function_signature)
        forbidden_seen = sorted(set(mandate.forbidden_effects) & observed_effects)
        checks.append(
            CheckResult(
                "intent_forbidden_effects",
                not forbidden_seen,
                (
                    "Proposal contains forbidden semantic effects: "
                    + ", ".join(forbidden_seen)
                    if forbidden_seen
                    else "Proposal does not contain a forbidden semantic effect."
                ),
            )
        )
    return checks


def infer_contract_effects(function_signature: str) -> set[str]:
    """Bounded semantic-effect vocabulary for the protocol profiles used by ProofPilot.

    Unknown functions are marked as unknown instead of being assumed side-effect free.
    """

    mapping = {
        "setUserEMode(uint8)": {"aave.user_emode"},
        "setUserUseReserveAsCollateral(address,bool)": {"aave.collateral_configuration"},
        "transfer(address,uint256)": {"erc20.balance_transfer"},
    }
    return set(mapping.get(function_signature, {"unknown.contract_effect"}))


def _resolve_path(state: dict[str, Any], path: str) -> Any:
    current: Any = state
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _flatten_state(state: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    leaves: list[tuple[str, Any]] = []
    for key in sorted(state):
        path = f"{prefix}.{key}" if prefix else key
        value = state[key]
        if isinstance(value, dict):
            leaves.extend(_flatten_state(value, path))
        else:
            leaves.append((path, value))
    return leaves


def _compare(observed: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return observed == expected
    if operator == "ne":
        return observed != expected
    if operator == "gte":
        return _safe_order(observed, expected, lambda a, b: a >= b)
    if operator == "lte":
        return _safe_order(observed, expected, lambda a, b: a <= b)
    if operator == "gt":
        return _safe_order(observed, expected, lambda a, b: a > b)
    if operator == "lt":
        return _safe_order(observed, expected, lambda a, b: a < b)
    if operator == "in":
        try:
            return observed in expected
        except TypeError:
            return False
    return False


def _safe_order(left: Any, right: Any, comparator: Any) -> bool:
    try:
        return bool(comparator(left, right))
    except (TypeError, ValueError):
        return False

