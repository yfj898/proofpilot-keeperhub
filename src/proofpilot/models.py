from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class ActionKind(str, Enum):
    TRANSFER_NATIVE = "transfer_native"


class RunState(str, Enum):
    PLANNED = "PLANNED"
    POLICY_APPROVED = "POLICY_APPROVED"
    POLICY_REJECTED = "POLICY_REJECTED"
    SIMULATED = "SIMULATED"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    VERIFIED = "VERIFIED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    RECOVERY_EXHAUSTED = "RECOVERY_EXHAUSTED"


@dataclass(frozen=True)
class ExecutionPlan:
    action: ActionKind
    chain_id: str
    recipient: str
    amount: Decimal
    asset: str = "native"
    intent: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class PolicyDecision:
    passed: bool
    checks: tuple[CheckResult, ...]

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(check.reason for check in self.checks if not check.passed)


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    checks: tuple[CheckResult, ...]

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(check.reason for check in self.checks if not check.passed)


class RecoveryAction(str, Enum):
    STOP = "STOP"
    RETRY_READ = "RETRY_READ"
    RETRY_STATUS = "RETRY_STATUS"
    RESIMULATE = "RESIMULATE"
    REPLAN = "REPLAN"


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    reason: str
    consume_attempt: bool
    safe_to_repeat_write: bool = False

