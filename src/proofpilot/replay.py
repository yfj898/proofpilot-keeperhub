from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from .intent import IntentMandate, ProposedAction
from .models import CheckResult, VerificationResult


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"Unsupported fingerprint value: {type(value).__name__}")


def proposal_fingerprint(mandate: IntentMandate, proposal: ProposedAction) -> str:
    payload = {"mandate": asdict(mandate), "proposal": asdict(proposal)}
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ReplayRecord:
    intent_id: str
    fingerprint: str


class IntentReplayGuard:
    """Semantic replay guard above KeeperHub's request-level idempotency."""

    def __init__(self) -> None:
        self._records: dict[str, ReplayRecord] = {}

    def check(self, mandate: IntentMandate, proposal: ProposedAction) -> VerificationResult:
        fingerprint = proposal_fingerprint(mandate, proposal)
        existing = self._records.get(mandate.intent_id)
        if existing is None:
            return VerificationResult(
                True,
                (CheckResult("intent_not_replayed", True, "Intent has not been consumed."),),
            )
        same = existing.fingerprint == fingerprint
        return VerificationResult(
            False,
            (
                CheckResult(
                    "intent_not_replayed",
                    False,
                    (
                        "Intent id has already been consumed by the same proposal."
                        if same
                        else "Intent id has already been consumed by a different proposal."
                    ),
                ),
            ),
        )

    def consume(self, mandate: IntentMandate, proposal: ProposedAction) -> ReplayRecord:
        decision = self.check(mandate, proposal)
        if not decision.passed:
            raise ValueError("intent replay detected")
        record = ReplayRecord(mandate.intent_id, proposal_fingerprint(mandate, proposal))
        self._records[mandate.intent_id] = record
        return record

    def contains(self, intent_id: str) -> bool:
        return intent_id in self._records
