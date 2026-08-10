from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from typing import Iterable

from .intent import (
    IntentAction,
    IntentMandate,
    ProposedAction,
    StateCondition,
    assure_intent,
    verify_state_conditions,
)


class ScenarioKind(str, Enum):
    SAFE = "safe"
    WRONG_CHAIN = "wrong_chain"
    WRONG_TARGET = "wrong_target"
    WRONG_AMOUNT = "wrong_amount"
    OVER_AMOUNT_CAP = "over_amount_cap"
    WRONG_FUNCTION = "wrong_function"
    WRONG_ARGUMENTS = "wrong_arguments"
    MALFORMED_TARGET = "malformed_target"
    STALE_PRECONDITION = "stale_precondition"
    POSTCONDITION_MISMATCH = "postcondition_mismatch"


@dataclass(frozen=True)
class BenchScenario:
    name: str
    kind: ScenarioKind
    mandate: IntentMandate
    proposal: ProposedAction
    should_approve: bool


@dataclass(frozen=True)
class BenchResult:
    scenario: BenchScenario
    approved: bool
    reasons: tuple[str, ...]

    @property
    def correct(self) -> bool:
        return self.approved == self.scenario.should_approve


@dataclass(frozen=True)
class BenchSummary:
    total: int
    correct: int
    unsafe_total: int
    unsafe_approved: int
    safe_total: int
    safe_rejected: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def unsafe_approval_rate(self) -> float:
        return self.unsafe_approved / self.unsafe_total if self.unsafe_total else 0.0

    @property
    def safe_rejection_rate(self) -> float:
        return self.safe_rejected / self.safe_total if self.safe_total else 0.0


@dataclass(frozen=True)
class StateBenchResult:
    name: str
    kind: ScenarioKind
    passed: bool
    should_pass: bool
    reasons: tuple[str, ...]

    @property
    def correct(self) -> bool:
        return self.passed == self.should_pass


def run_keeperbench(scenarios: Iterable[BenchScenario]) -> tuple[list[BenchResult], BenchSummary]:
    results: list[BenchResult] = []
    for scenario in scenarios:
        decision = assure_intent(scenario.mandate, scenario.proposal)
        results.append(
            BenchResult(
                scenario=scenario,
                approved=decision.passed,
                reasons=decision.reasons,
            )
        )

    total = len(results)
    correct = sum(result.correct for result in results)
    unsafe = [result for result in results if not result.scenario.should_approve]
    safe = [result for result in results if result.scenario.should_approve]
    summary = BenchSummary(
        total=total,
        correct=correct,
        unsafe_total=len(unsafe),
        unsafe_approved=sum(result.approved for result in unsafe),
        safe_total=len(safe),
        safe_rejected=sum(not result.approved for result in safe),
    )
    return results, summary


def default_transfer_suite(
    *,
    target: str,
    wrong_target: str,
    amount: Decimal = Decimal("0.000001"),
    max_amount: Decimal = Decimal("0.00001"),
) -> list[BenchScenario]:
    mandate = IntentMandate(
        intent_id="keeperbench-transfer-v1",
        action=IntentAction.TRANSFER_NATIVE,
        target=target,
        exact_amount=amount,
        max_amount=max_amount,
        description="Transfer the exact tiny Base Sepolia test amount to the approved address.",
    )
    safe = ProposedAction(
        action=IntentAction.TRANSFER_NATIVE,
        chain_id=mandate.chain_id,
        target=target,
        amount=amount,
    )
    return [
        BenchScenario("safe_exact", ScenarioKind.SAFE, mandate, safe, True),
        BenchScenario("wrong_chain", ScenarioKind.WRONG_CHAIN, mandate, replace(safe, chain_id="1"), False),
        BenchScenario("wrong_target", ScenarioKind.WRONG_TARGET, mandate, replace(safe, target=wrong_target), False),
        BenchScenario("wrong_amount", ScenarioKind.WRONG_AMOUNT, mandate, replace(safe, amount=amount * 2), False),
        BenchScenario("over_amount_cap", ScenarioKind.OVER_AMOUNT_CAP, mandate, replace(safe, amount=max_amount * 2), False),
        BenchScenario("malformed_target", ScenarioKind.MALFORMED_TARGET, mandate, replace(safe, target="0x1234"), False),
    ]


def default_contract_suite(*, target: str, wrong_target: str) -> list[BenchScenario]:
    mandate = IntentMandate(
        intent_id="keeperbench-contract-v1",
        action=IntentAction.CONTRACT_CALL,
        target=target,
        function_signature="setThreshold(uint256)",
        exact_arguments=(20,),
        description="Set threshold to exactly 20 on the approved Base Sepolia contract.",
    )
    safe = ProposedAction(
        action=IntentAction.CONTRACT_CALL,
        chain_id=mandate.chain_id,
        target=target,
        function_signature="setThreshold(uint256)",
        arguments=(20,),
    )
    return [
        BenchScenario("contract_safe_exact", ScenarioKind.SAFE, mandate, safe, True),
        BenchScenario("contract_wrong_target", ScenarioKind.WRONG_TARGET, mandate, replace(safe, target=wrong_target), False),
        BenchScenario(
            "contract_wrong_function",
            ScenarioKind.WRONG_FUNCTION,
            mandate,
            replace(safe, function_signature="setPaused(bool)", arguments=(True,)),
            False,
        ),
        BenchScenario("contract_wrong_arguments", ScenarioKind.WRONG_ARGUMENTS, mandate, replace(safe, arguments=(200,)), False),
    ]


def run_state_semantics_suite() -> list[StateBenchResult]:
    preconditions = (StateCondition("config.paused", "eq", False),)
    postconditions = (
        StateCondition("config.threshold", "eq", 20),
        StateCondition("config.paused", "eq", False),
    )
    cases = [
        ("pre_safe", ScenarioKind.SAFE, preconditions, {"config": {"paused": False}}, True, "pre"),
        (
            "pre_stale_paused",
            ScenarioKind.STALE_PRECONDITION,
            preconditions,
            {"config": {"paused": True}},
            False,
            "pre",
        ),
        (
            "post_safe",
            ScenarioKind.SAFE,
            postconditions,
            {"config": {"threshold": 20, "paused": False}},
            True,
            "post",
        ),
        (
            "post_wrong_threshold",
            ScenarioKind.POSTCONDITION_MISMATCH,
            postconditions,
            {"config": {"threshold": 200, "paused": False}},
            False,
            "post",
        ),
        (
            "post_invariant_broken",
            ScenarioKind.POSTCONDITION_MISMATCH,
            postconditions,
            {"config": {"threshold": 20, "paused": True}},
            False,
            "post",
        ),
    ]
    results: list[StateBenchResult] = []
    for name, kind, conditions, state, should_pass, phase in cases:
        decision = verify_state_conditions(conditions, state, phase=phase)
        results.append(StateBenchResult(name, kind, decision.passed, should_pass, decision.reasons))
    return results

