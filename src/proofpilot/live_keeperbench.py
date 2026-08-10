from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class LiveBenchResult:
    name: str
    category: str
    expectation: str
    correct: bool
    primary_write_calls: int = 0
    adversary_write_calls: int = 0
    transaction_hashes: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveBenchSummary:
    total: int
    correct: int
    prewrite_attack_total: int
    prewrite_attack_escaped: int
    race_total: int
    race_detected: int
    replay_total: int
    replay_contained: int
    evidence_tamper_total: int
    evidence_tamper_detected: int
    recovery_total: int
    recovery_succeeded: int
    primary_write_calls: int
    adversary_write_calls: int
    unique_transactions: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def unsafe_approval_rate(self) -> float:
        return (
            self.prewrite_attack_escaped / self.prewrite_attack_total
            if self.prewrite_attack_total
            else 0.0
        )

    @property
    def prewrite_containment_rate(self) -> float:
        return 1.0 - self.unsafe_approval_rate if self.prewrite_attack_total else 0.0

    @property
    def race_detection_rate(self) -> float:
        return self.race_detected / self.race_total if self.race_total else 0.0

    @property
    def replay_containment_rate(self) -> float:
        return self.replay_contained / self.replay_total if self.replay_total else 0.0

    @property
    def evidence_tamper_detection_rate(self) -> float:
        return (
            self.evidence_tamper_detected / self.evidence_tamper_total
            if self.evidence_tamper_total
            else 0.0
        )

    @property
    def recovery_success_rate(self) -> float:
        return self.recovery_succeeded / self.recovery_total if self.recovery_total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "correct": self.correct,
            "accuracy": self.accuracy,
            "prewrite_attack_total": self.prewrite_attack_total,
            "prewrite_attack_escaped": self.prewrite_attack_escaped,
            "unsafe_approval_rate": self.unsafe_approval_rate,
            "prewrite_containment_rate": self.prewrite_containment_rate,
            "race_total": self.race_total,
            "race_detected": self.race_detected,
            "race_detection_rate": self.race_detection_rate,
            "replay_total": self.replay_total,
            "replay_contained": self.replay_contained,
            "replay_containment_rate": self.replay_containment_rate,
            "evidence_tamper_total": self.evidence_tamper_total,
            "evidence_tamper_detected": self.evidence_tamper_detected,
            "evidence_tamper_detection_rate": self.evidence_tamper_detection_rate,
            "recovery_total": self.recovery_total,
            "recovery_succeeded": self.recovery_succeeded,
            "recovery_success_rate": self.recovery_success_rate,
            "primary_write_calls": self.primary_write_calls,
            "adversary_write_calls": self.adversary_write_calls,
            "unique_transactions": self.unique_transactions,
        }


PREWRITE_CATEGORIES = {"semantic_prewrite", "freshness_prewrite"}
RACE_CATEGORIES = {"freshness_prewrite", "postwrite_drift"}
REPLAY_CATEGORIES = {"semantic_replay", "transport_idempotency"}
EVIDENCE_CATEGORIES = {"evidence_tamper"}
RECOVERY_CATEGORIES = {"semantic_recovery"}


LIVE_SCENARIO_NAMES: tuple[str, ...] = (
    "safe_live_control",
    "wrong_chain",
    "wrong_target",
    "wrong_function",
    "wrong_arguments",
    "malformed_target",
    "stale_snapshot_before_simulation",
    "simulation_execution_race",
    "duplicate_semantic_intent",
    "keeperhub_idempotency_replay",
    "post_state_drift",
    "receipt_hash_tampering",
    "proof_bundle_tampering",
    "semantic_recovery_after_drift",
    "fresh_intent_same_action",
)


def summarize_live_results(results: Iterable[LiveBenchResult]) -> LiveBenchSummary:
    rows = list(results)
    prewrite = [r for r in rows if r.category in PREWRITE_CATEGORIES]
    races = [r for r in rows if r.category in RACE_CATEGORIES]
    replays = [r for r in rows if r.category in REPLAY_CATEGORIES]
    evidence = [r for r in rows if r.category in EVIDENCE_CATEGORIES]
    recovery = [r for r in rows if r.category in RECOVERY_CATEGORIES]
    txs = {
        tx.lower()
        for row in rows
        for tx in row.transaction_hashes
        if isinstance(tx, str) and tx.startswith("0x")
    }
    return LiveBenchSummary(
        total=len(rows),
        correct=sum(r.correct for r in rows),
        prewrite_attack_total=len(prewrite),
        prewrite_attack_escaped=sum(r.primary_write_calls > 0 for r in prewrite),
        race_total=len(races),
        race_detected=sum(r.correct for r in races),
        replay_total=len(replays),
        replay_contained=sum(r.correct for r in replays),
        evidence_tamper_total=len(evidence),
        evidence_tamper_detected=sum(r.correct for r in evidence),
        recovery_total=len(recovery),
        recovery_succeeded=sum(r.correct for r in recovery),
        primary_write_calls=sum(r.primary_write_calls for r in rows),
        adversary_write_calls=sum(r.adversary_write_calls for r in rows),
        unique_transactions=len(txs),
    )
