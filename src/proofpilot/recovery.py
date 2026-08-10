from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import RecoveryAction, RecoveryDecision


class FailureKind(str, Enum):
    POLICY_REJECTED = "POLICY_REJECTED"
    AUTHENTICATION = "AUTHENTICATION"
    INVALID_REQUEST = "INVALID_REQUEST"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    SIMULATION_REVERT = "SIMULATION_REVERT"
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    RATE_LIMITED = "RATE_LIMITED"
    EXECUTION_PENDING_TIMEOUT = "EXECUTION_PENDING_TIMEOUT"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    STALE_STATE = "STALE_STATE"
    VERIFICATION_READ_FAILED = "VERIFICATION_READ_FAILED"
    POSTCONDITION_FAILED = "POSTCONDITION_FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RecoveryContext:
    kind: FailureKind
    attempt: int = 0
    max_attempts: int = 2

    @property
    def exhausted(self) -> bool:
        return self.attempt >= self.max_attempts


class RecoveryPolicy:
    """Fail-closed recovery rules.

    No recovery decision in this MVP repeats an onchain write automatically.  A
    transient error may re-read status/state, and stale state may re-simulate, but a
    second broadcast always requires the caller to re-enter the admission path.
    """

    def decide(self, context: RecoveryContext) -> RecoveryDecision:
        if context.exhausted:
            return RecoveryDecision(
                RecoveryAction.STOP,
                "Recovery budget exhausted.",
                consume_attempt=False,
            )

        if context.kind in {
            FailureKind.POLICY_REJECTED,
            FailureKind.AUTHENTICATION,
            FailureKind.INVALID_REQUEST,
            FailureKind.INSUFFICIENT_BALANCE,
            FailureKind.SIMULATION_REVERT,
        }:
            return RecoveryDecision(
                RecoveryAction.STOP,
                f"{context.kind.value} requires operator/configuration intervention.",
                consume_attempt=False,
            )

        if context.kind in {FailureKind.TRANSIENT_NETWORK, FailureKind.RATE_LIMITED}:
            return RecoveryDecision(
                RecoveryAction.RETRY_READ,
                "Retry a non-writing read/tool call after backoff.",
                consume_attempt=True,
            )

        if context.kind == FailureKind.EXECUTION_PENDING_TIMEOUT:
            return RecoveryDecision(
                RecoveryAction.RETRY_STATUS,
                "Execution may already have been broadcast; query status instead of rebroadcasting.",
                consume_attempt=True,
                safe_to_repeat_write=False,
            )

        if context.kind == FailureKind.STALE_STATE:
            return RecoveryDecision(
                RecoveryAction.RESIMULATE,
                "Refresh state and re-simulate before any new write decision.",
                consume_attempt=True,
                safe_to_repeat_write=False,
            )

        if context.kind == FailureKind.VERIFICATION_READ_FAILED:
            return RecoveryDecision(
                RecoveryAction.RETRY_READ,
                "Retry the independent postcondition read; do not rebroadcast.",
                consume_attempt=True,
                safe_to_repeat_write=False,
            )

        if context.kind == FailureKind.POSTCONDITION_FAILED:
            return RecoveryDecision(
                RecoveryAction.REPLAN,
                "Execution evidence and intended state disagree; stop writes and create a new plan.",
                consume_attempt=True,
                safe_to_repeat_write=False,
            )

        if context.kind == FailureKind.EXECUTION_FAILED:
            return RecoveryDecision(
                RecoveryAction.REPLAN,
                "Terminal execution failure requires diagnosis and a fresh admission cycle.",
                consume_attempt=True,
                safe_to_repeat_write=False,
            )

        return RecoveryDecision(
            RecoveryAction.STOP,
            "Unknown failure class; fail closed.",
            consume_attempt=False,
        )


def classify_failure(*, message: str = "", status_code: int | None = None) -> FailureKind:
    text = message.lower()
    if status_code in {401, 403} or "invalid_token" in text or "authentication" in text:
        return FailureKind.AUTHENTICATION
    if status_code == 429 or "rate limit" in text or "too many requests" in text:
        return FailureKind.RATE_LIMITED
    if "insufficient" in text and "balance" in text:
        return FailureKind.INSUFFICIENT_BALANCE
    if "wouldrevert" in text or "would revert" in text or "revert" in text:
        return FailureKind.SIMULATION_REVERT
    if "timeout" in text or "timed out" in text:
        return FailureKind.TRANSIENT_NETWORK
    if status_code is not None and 400 <= status_code < 500:
        return FailureKind.INVALID_REQUEST
    if status_code is not None and status_code >= 500:
        return FailureKind.TRANSIENT_NETWORK
    return FailureKind.UNKNOWN

