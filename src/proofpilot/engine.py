from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .mcp import McpError
from .models import ExecutionPlan, PolicyDecision, RecoveryDecision, RunState, VerificationResult
from .policy import PolicyEngine
from .recovery import FailureKind, RecoveryContext, RecoveryPolicy, classify_failure
from .verifier import verify_simulation, verify_terminal_execution


class TransferExecutor(Protocol):
    def simulate_native_transfer(self, *, recipient: str, amount: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class EngineOutcome:
    state: RunState
    policy: PolicyDecision
    simulation: dict[str, Any] | None = None
    verification: VerificationResult | None = None
    recovery: RecoveryDecision | None = None
    error: str = ""


class ProofPilotEngine:
    """Deterministic admission + simulation coordinator.

    The engine is intentionally write-free.  It proves the pre-broadcast safety path:
    plan -> policy -> KeeperHub simulation -> simulation verification -> recovery.
    Broadcast remains an explicit later action so no model output can silently cross
    the write boundary.
    """

    def __init__(
        self,
        executor: TransferExecutor,
        *,
        policy: PolicyEngine | None = None,
        recovery: RecoveryPolicy | None = None,
    ):
        self.executor = executor
        self.policy = policy or PolicyEngine()
        self.recovery = recovery or RecoveryPolicy()

    def admit_and_simulate(self, plan: ExecutionPlan, *, recovery_attempt: int = 0) -> EngineOutcome:
        policy_decision = self.policy.evaluate(plan)
        if not policy_decision.passed:
            recovery_decision = self.recovery.decide(
                RecoveryContext(FailureKind.POLICY_REJECTED, attempt=recovery_attempt)
            )
            return EngineOutcome(
                state=RunState.POLICY_REJECTED,
                policy=policy_decision,
                recovery=recovery_decision,
                error="; ".join(policy_decision.reasons),
            )

        try:
            simulation = self.executor.simulate_native_transfer(
                recipient=plan.recipient,
                amount=format(plan.amount, "f"),
            )
        except McpError as exc:
            kind = classify_failure(message=_error_text(exc), status_code=exc.status)
            recovery_decision = self.recovery.decide(
                RecoveryContext(kind, attempt=recovery_attempt)
            )
            return EngineOutcome(
                state=RunState.SIMULATION_FAILED,
                policy=policy_decision,
                recovery=recovery_decision,
                error=str(exc),
            )

        verification = verify_simulation(simulation)
        if not verification.passed:
            recovery_decision = self.recovery.decide(
                RecoveryContext(FailureKind.SIMULATION_REVERT, attempt=recovery_attempt)
            )
            return EngineOutcome(
                state=RunState.SIMULATION_FAILED,
                policy=policy_decision,
                simulation=simulation,
                verification=verification,
                recovery=recovery_decision,
                error="; ".join(verification.reasons),
            )

        return EngineOutcome(
            state=RunState.SIMULATED,
            policy=policy_decision,
            simulation=simulation,
            verification=verification,
        )


def verify_execution_status(status: dict[str, Any], *, recovery_attempt: int = 0) -> tuple[VerificationResult, RecoveryDecision | None]:
    verification = verify_terminal_execution(status)
    if verification.passed:
        return verification, None
    decision = RecoveryPolicy().decide(
        RecoveryContext(FailureKind.EXECUTION_FAILED, attempt=recovery_attempt)
    )
    return verification, decision


def _error_text(exc: McpError) -> str:
    if exc.body is None:
        return str(exc)
    return f"{exc} {exc.body}"

