from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from keeperbench_attackers.heldout import generate_heldout_cases

from .intent import (
    IntentAction,
    IntentMandate,
    ProposedAction,
    assure_intent,
    verify_state_snapshot_fresh,
)
from .intent_ir import DelegationEnvelope, IntentEnvelope, IntentIRAction, verify_delegation


@dataclass(frozen=True)
class BlindEvaluation:
    evaluator: str
    total: int
    unsafe_approved: int

    @property
    def unsafe_approval_rate(self) -> float:
        return self.unsafe_approved / self.total if self.total else 0.0


def _hash_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        digest.update(str(path.name).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_frozen_manifest(root: Path, *, seed: int, trials: int) -> dict[str, Any]:
    defender_paths = [
        root / "src/proofpilot/intent.py",
        root / "src/proofpilot/intent_ir.py",
        root / "src/proofpilot/mandate_compiler.py",
    ]
    attacker_path = root / "src/keeperbench_attackers/heldout.py"
    return {
        "schema": "proofpilot.keeperbench.blind.v1",
        "seed": seed,
        "trials": trials,
        "defender_source_sha256": _hash_files(defender_paths),
        "attacker_source_sha256": _hash_files([attacker_path]),
        "attacker_imports_defender": "proofpilot" in attacker_path.read_text(encoding="utf-8").lower(),
    }


def generate_blind_cases(*, target: str, seed: int, trials: int, now: int = 2_000_000_000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trial in range(trials):
        goal = 1000 + ((seed + trial * 7919) % 900000)
        base = {
            "case_id": f"blind-{trial:04d}",
            "now": now,
            "deadline": now + 600,
            "target": target,
            "goal": goal,
            "proposal": {
                "chain_id": "84532",
                "target": target,
                "function_signature": "storeNumber(uint256)",
                "arguments": [goal],
                "native_value": "0",
            },
            "expected_state": {"config": {"number": goal - 1}},
            "observed_state": {"config": {"number": goal - 1}},
        }
        rows.extend(generate_heldout_cases(base, seed=seed + trial))
    return rows


def evaluate_blind_cases(cases: list[dict[str, Any]], *, target: str) -> list[BlindEvaluation]:
    def execution_only(row: dict[str, Any]) -> bool:
        proposal = row["proposal"]
        return isinstance(proposal.get("target"), str) and proposal["target"].startswith("0x")

    def static_allowlist(row: dict[str, Any]) -> bool:
        proposal = row["proposal"]
        return (
            proposal.get("chain_id") == "84532"
            and str(proposal.get("target", "")).lower() == target.lower()
            and proposal.get("function_signature") == "storeNumber(uint256)"
        )

    def semantic(row: dict[str, Any]) -> bool:
        proposal_data = row["proposal"]
        mandate = IntentMandate(
            intent_id=row["case_id"],
            action=IntentAction.CONTRACT_CALL,
            target=target,
            function_signature="storeNumber(uint256)",
            exact_arguments=(row["goal"],),
            exact_native_value=Decimal("0"),
        )
        proposal = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id=proposal_data["chain_id"],
            target=proposal_data["target"],
            function_signature=proposal_data["function_signature"],
            arguments=tuple(proposal_data["arguments"]),
            native_value=Decimal(str(proposal_data.get("native_value", "0"))),
        )
        action_ok = assure_intent(mandate, proposal).passed
        fresh = verify_state_snapshot_fresh(row["expected_state"], row["observed_state"]).passed
        delegation = DelegationEnvelope(
            delegation_id="blind",
            allowed_protocols=frozenset({"storage"}),
            allowed_targets=frozenset({target}),
            allowed_functions=frozenset({"storeNumber(uint256)"}),
            max_native_value=Decimal("0"),
            expires_at=row["now"] + 3600,
        )
        ir = IntentEnvelope(
            intent_id=row["case_id"],
            source_text="blind held-out case",
            action=IntentIRAction(
                protocol="storage",
                target=proposal.target,
                function_signature=proposal.function_signature,
                arguments=proposal.arguments,
                native_value=proposal.native_value,
            ),
            deadline=row["deadline"],
        )
        delegated = verify_delegation(delegation, ir, now=row["now"]).passed
        return action_ok and fresh and delegated

    evaluators: tuple[tuple[str, Callable[[dict[str, Any]], bool]], ...] = (
        ("execution_only", execution_only),
        ("static_allowlist", static_allowlist),
        ("proofpilot", semantic),
    )
    return [
        BlindEvaluation(name, len(cases), sum(fn(row) for row in cases))
        for name, fn in evaluators
    ]


def build_blind_artifact(root: Path, *, target: str, seed: int, trials: int) -> dict[str, Any]:
    manifest = build_frozen_manifest(root, seed=seed, trials=trials)
    cases = generate_blind_cases(target=target, seed=seed, trials=trials)
    evaluations = evaluate_blind_cases(cases, target=target)
    manifest["generated_cases"] = len(cases)
    manifest["attack_families"] = sorted({row["attack"] for row in cases})
    manifest["evaluators"] = [
        {
            "evaluator": item.evaluator,
            "total": item.total,
            "unsafe_approved": item.unsafe_approved,
            "unsafe_approval_rate": item.unsafe_approval_rate,
        }
        for item in evaluations
    ]
    manifest["cases_sha256"] = hashlib.sha256(
        json.dumps(cases, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return manifest

