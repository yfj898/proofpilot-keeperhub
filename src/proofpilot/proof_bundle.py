from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


EXECUTION_TRACE_SCHEMA = "proofpilot.execution-trace.v2"
VERIFICATION_LEVEL_L2_EFFECT = "L2_EXECUTION_EFFECT_VERIFIED"
EXECUTION_TRACE_STATUSES = frozenset(
    {
        "BLOCKED",
        "SIMULATED",
        "SIMULATION_FAILED",
        "EXECUTION_FAILED",
        "VERIFICATION_FAILED",
        "VERIFIED",
    }
)

_SENSITIVE_KEY_NAMES = frozenset(
    {
        "api_key",
        "kh_api_key",
        "guardian_llm_api_key",
        "authorization_header",
        "http_authorization",
        "private_key",
        "secret",
        "client_secret",
        "mnemonic",
        "seed_phrase",
        "bearer_token",
        "access_token",
        "refresh_token",
    }
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\bkh_[A-Za-z0-9_+/.=-]{12,}\b"),
    re.compile(r"\bnvapi-[A-Za-z0-9_-]{12,}\b"),
)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(type(value).__name__)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contains_sensitive_material(value: Any, *, parent_key: str = "") -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in _SENSITIVE_KEY_NAMES or key_text.endswith("_private_key"):
                return True
            if _contains_sensitive_material(item, parent_key=key_text):
                return True
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_sensitive_material(item, parent_key=parent_key) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS)
    return False


def _trace_semantics_valid(trace: dict[str, Any]) -> bool:
    status = trace.get("final_status")
    if status not in EXECUTION_TRACE_STATUSES:
        return False
    # Pre-write terminal states must never be able to claim that a transaction was
    # broadcast. This is especially important for Observe mode, whose canonical
    # terminal state is SIMULATED.
    if status in {"BLOCKED", "SIMULATED", "SIMULATION_FAILED"} and trace.get(
        "broadcast_attempted"
    ) is True:
        return False
    if status != "VERIFIED":
        return True

    keeperhub_execution = trace.get("keeperhub", {}).get("execution", {})
    terminal_check = keeperhub_execution.get("terminal_check", {})
    verification = trace.get("verification", {})
    receipt = verification.get("independent_receipt", {})
    postcondition = verification.get("postcondition_check", {})
    base_verified = (
        trace.get("broadcast_attempted") is True
        and terminal_check.get("passed") is True
        and receipt.get("passed") is True
        and postcondition.get("passed") is True
    )
    if not base_verified:
        return False
    profile = trace.get("context", {}).get("verification_profile")
    if profile == "authorization_to_execution_v1":
        binding = verification.get("execution_binding", {})
        payload = trace.get("authorization", {}).get("execution_payload", {})
        return (
            binding.get("passed") is True
            and payload.get("commitment_match") is True
            and verification.get("level") == VERIFICATION_LEVEL_L2_EFFECT
        )
    return True


def build_execution_trace_v2(
    *,
    user_intent: str,
    intent_ir: dict[str, Any],
    intent_commitment: str,
    proposal: dict[str, Any],
    intent_assurance: dict[str, Any],
    pre_state: dict[str, Any],
    keeperhub_simulation: dict[str, Any],
    final_status: str,
    broadcast_attempted: bool,
    network: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    precondition_checks: list[dict[str, Any]] | None = None,
    freshness_check: dict[str, Any] | None = None,
    semantic_deviations: list[str] | None = None,
    execution_payload: dict[str, Any] | None = None,
    keeperhub_execution: dict[str, Any] | None = None,
    independent_receipt: dict[str, Any] | None = None,
    execution_binding: dict[str, Any] | None = None,
    verification_level: str = "",
    post_state: dict[str, Any] | None = None,
    postcondition_check: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    final_reason: str = "",
    trace_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build one tamper-evident trace from user intent through verified outcome.

    The builder deliberately refuses to mint a VERIFIED trace unless KeeperHub reached a
    successful terminal state, an independent receipt check passed, and postconditions passed.
    It also rejects common credential fields/key shapes so secrets cannot silently enter artifacts.
    """

    trace: dict[str, Any] = {
        "schema": EXECUTION_TRACE_SCHEMA,
        "trace_id": trace_id or f"pp_{uuid.uuid4().hex}",
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "testnet_only": True,
        "network": network or {"name": "Base Sepolia", "chain_id": "84532"},
        "context": context or {},
        "intent": {
            "source_text": user_intent,
            "source_text_sha256": hashlib.sha256(user_intent.encode("utf-8")).hexdigest(),
            "commitment": intent_commitment,
            "ir": intent_ir,
        },
        "proposal": {
            "sha256": _canonical_sha256(proposal),
            "action": proposal,
        },
        "authorization": {
            "intent_assurance": intent_assurance,
            "precondition_checks": precondition_checks or [],
            "freshness_check": freshness_check or {},
            "independent_semantic_deviations": semantic_deviations or [],
            "execution_payload": execution_payload or {},
        },
        "pre_state": pre_state,
        "keeperhub": {
            "simulation": keeperhub_simulation,
            "execution": keeperhub_execution or {},
        },
        "verification": {
            "level": verification_level,
            "independent_receipt": independent_receipt or {},
            "execution_binding": execution_binding or {},
            "post_state": post_state or {},
            "postcondition_check": postcondition_check or {},
        },
        "provenance": provenance or {},
        "broadcast_attempted": bool(broadcast_attempted),
        "final_status": final_status,
        "final_reason": final_reason,
    }
    if not _trace_semantics_valid(trace):
        raise ValueError("Execution trace final status is inconsistent with its evidence.")
    if _contains_sensitive_material(trace):
        raise ValueError("Execution trace contains secret-like material and cannot be serialized.")
    trace["sha256"] = _canonical_sha256(trace)
    return trace


def verify_execution_trace_v2(trace: dict[str, Any]) -> bool:
    if trace.get("schema") != EXECUTION_TRACE_SCHEMA:
        return False
    claimed = trace.get("sha256")
    if not isinstance(claimed, str) or len(claimed) != 64:
        return False
    unsigned = dict(trace)
    unsigned.pop("sha256", None)
    if _contains_sensitive_material(unsigned) or not _trace_semantics_valid(unsigned):
        return False
    return claimed == _canonical_sha256(unsigned)


def build_intent_proof_bundle(
    *,
    intent_id: str,
    chain_id: str,
    target: str,
    mandate: dict[str, Any],
    proposal: dict[str, Any],
    pre_state: dict[str, Any],
    simulation: dict[str, Any],
    keeperhub_execution: dict[str, Any],
    independent_receipt: dict[str, Any],
    post_state: dict[str, Any],
    checks: dict[str, bool],
    created_at: str | None = None,
) -> dict[str, Any]:
    """Create a tamper-evident, JSON-serializable intent execution proof."""

    bundle: dict[str, Any] = {
        "schema": "proofpilot.intent-proof.v1",
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "intent_id": intent_id,
        "network": {"name": "Base Sepolia", "chain_id": chain_id},
        "target": target,
        "mandate": mandate,
        "proposal": proposal,
        "pre_state": pre_state,
        "simulation": simulation,
        "keeperhub_execution": keeperhub_execution,
        "independent_receipt": independent_receipt,
        "post_state": post_state,
        "checks": checks,
        "verified": bool(checks) and all(checks.values()),
    }
    digest_input = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    bundle["sha256"] = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return bundle


def verify_intent_proof_bundle(bundle: dict[str, Any]) -> bool:
    claimed = bundle.get("sha256")
    if not isinstance(claimed, str) or len(claimed) != 64:
        return False
    unsigned = dict(bundle)
    unsigned.pop("sha256", None)
    digest_input = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    expected = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return claimed == expected

