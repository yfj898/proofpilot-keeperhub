from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any, Iterable

from .adversarial import GeneratedAdversarialCase
from .baselines import CaseEvaluator


@dataclass(frozen=True)
class EvaluatedCase:
    evaluator: str
    trial_id: int
    case_id: str
    attack: str
    expected_approval: bool
    approved: bool
    correct: bool


@dataclass(frozen=True)
class EvaluatorSummary:
    evaluator: str
    total: int
    correct: int
    safe_total: int
    safe_approved: int
    unsafe_total: int
    unsafe_approved: int
    accuracy: float
    safe_acceptance_rate: float
    unsafe_approval_rate: float
    unsafe_approval_ci95: tuple[float, float]
    trial_unsafe_approval_mean: float
    trial_unsafe_approval_min: float
    trial_unsafe_approval_max: float


def evaluate_cases(
    cases: Iterable[GeneratedAdversarialCase],
    evaluators: Iterable[CaseEvaluator],
) -> tuple[list[EvaluatedCase], list[EvaluatorSummary]]:
    rows: list[EvaluatedCase] = []
    case_list = list(cases)
    evaluator_list = list(evaluators)
    for evaluator in evaluator_list:
        for case in case_list:
            decision = evaluator.evaluate(case)
            rows.append(
                EvaluatedCase(
                    evaluator=evaluator.name,
                    trial_id=case.trial_id,
                    case_id=case.case_id,
                    attack=case.attack.value,
                    expected_approval=case.should_approve,
                    approved=decision.approved,
                    correct=decision.approved == case.should_approve,
                )
            )
    names = [evaluator.name for evaluator in evaluator_list]
    return rows, [_summarize(name, rows) for name in names]


def comparison_artifact(
    *,
    trials: int,
    seed: int,
    target: str,
    rows: list[EvaluatedCase],
    summaries: list[EvaluatorSummary],
    live_simulation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "proofpilot.keeperbench.v2.1",
        "trials": trials,
        "seed": seed,
        "target": target,
        "generated_cases": len(rows) // len(summaries) if summaries else 0,
        "evaluators": [summary_to_dict(summary) for summary in summaries],
        "attack_breakdown": attack_breakdown(rows),
        "live_simulation": live_simulation or {},
    }


def summary_to_dict(summary: EvaluatorSummary) -> dict[str, Any]:
    payload = asdict(summary)
    payload["unsafe_approval_ci95"] = list(summary.unsafe_approval_ci95)
    return payload


def attack_breakdown(rows: Iterable[EvaluatedCase]) -> dict[str, dict[str, dict[str, float | int]]]:
    table: dict[str, dict[str, dict[str, float | int]]] = {}
    for row in rows:
        by_attack = table.setdefault(row.evaluator, {})
        cell = by_attack.setdefault(row.attack, {"total": 0, "approved": 0, "correct": 0})
        cell["total"] = int(cell["total"]) + 1
        cell["approved"] = int(cell["approved"]) + int(row.approved)
        cell["correct"] = int(cell["correct"]) + int(row.correct)
    for by_attack in table.values():
        for cell in by_attack.values():
            total = int(cell["total"])
            cell["approval_rate"] = int(cell["approved"]) / total if total else 0.0
            cell["accuracy"] = int(cell["correct"]) / total if total else 0.0
    return table


def _summarize(evaluator: str, all_rows: list[EvaluatedCase]) -> EvaluatorSummary:
    rows = [row for row in all_rows if row.evaluator == evaluator]
    safe = [row for row in rows if row.expected_approval]
    unsafe = [row for row in rows if not row.expected_approval]
    unsafe_approved = sum(row.approved for row in unsafe)

    trial_ids = sorted({row.trial_id for row in rows})
    trial_uars: list[float] = []
    for trial_id in trial_ids:
        trial_unsafe = [row for row in unsafe if row.trial_id == trial_id]
        if trial_unsafe:
            trial_uars.append(sum(row.approved for row in trial_unsafe) / len(trial_unsafe))

    unsafe_rate = unsafe_approved / len(unsafe) if unsafe else 0.0
    return EvaluatorSummary(
        evaluator=evaluator,
        total=len(rows),
        correct=sum(row.correct for row in rows),
        safe_total=len(safe),
        safe_approved=sum(row.approved for row in safe),
        unsafe_total=len(unsafe),
        unsafe_approved=unsafe_approved,
        accuracy=sum(row.correct for row in rows) / len(rows) if rows else 0.0,
        safe_acceptance_rate=sum(row.approved for row in safe) / len(safe) if safe else 0.0,
        unsafe_approval_rate=unsafe_rate,
        unsafe_approval_ci95=_wilson_interval(unsafe_approved, len(unsafe)),
        trial_unsafe_approval_mean=mean(trial_uars) if trial_uars else 0.0,
        trial_unsafe_approval_min=min(trial_uars) if trial_uars else 0.0,
        trial_unsafe_approval_max=max(trial_uars) if trial_uars else 0.0,
    )


def _wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    lower = max(0.0, centre - margin)
    upper = min(1.0, centre + margin)
    if successes == 0:
        lower = 0.0
    if successes == n:
        upper = 1.0
    return (lower, upper)
