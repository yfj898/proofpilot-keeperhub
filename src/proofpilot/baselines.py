from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .adversarial import GeneratedAdversarialCase
from .intent import IntentAction, assure_intent, verify_state_snapshot_fresh
from .policy import looks_like_evm_address


@dataclass(frozen=True)
class BaselineDecision:
    approved: bool
    reason: str


class CaseEvaluator(Protocol):
    name: str

    def evaluate(self, case: GeneratedAdversarialCase) -> BaselineDecision: ...


class ExecutionOnlyBaseline:
    """Approximate an execution layer with no knowledge of the user's mandate."""

    name = "execution_only"

    def evaluate(self, case: GeneratedAdversarialCase) -> BaselineDecision:
        proposal = case.proposal
        approved = (
            proposal.action == IntentAction.CONTRACT_CALL
            and looks_like_evm_address(proposal.target)
            and bool(proposal.function_signature)
        )
        return BaselineDecision(approved, "structurally callable" if approved else "invalid call shape")


class StaticAllowlistBaseline:
    """Check static routing constraints, but not argument semantics or state freshness."""

    name = "static_allowlist"

    def evaluate(self, case: GeneratedAdversarialCase) -> BaselineDecision:
        m = case.mandate
        p = case.proposal
        approved = (
            p.action == m.action
            and p.chain_id == m.chain_id
            and looks_like_evm_address(p.target)
            and p.target.lower() == m.target.lower()
            and p.function_signature == m.function_signature
        )
        return BaselineDecision(approved, "static route accepted" if approved else "static route rejected")


class ProofPilotSemanticBaseline:
    """Full pre-write semantic assurance used by ProofPilot 2.1."""

    name = "proofpilot"

    def evaluate(self, case: GeneratedAdversarialCase) -> BaselineDecision:
        intent = assure_intent(case.mandate, case.proposal)
        if not intent.passed:
            return BaselineDecision(False, "; ".join(intent.reasons))
        freshness = verify_state_snapshot_fresh(
            case.expected_snapshot,
            case.observed_snapshot,
            phase="kb21_fresh",
        )
        if not freshness.passed:
            return BaselineDecision(False, "; ".join(freshness.reasons))
        return BaselineDecision(True, "intent and state snapshot verified")


def default_baselines() -> tuple[CaseEvaluator, ...]:
    return (
        ExecutionOnlyBaseline(),
        StaticAllowlistBaseline(),
        ProofPilotSemanticBaseline(),
    )
