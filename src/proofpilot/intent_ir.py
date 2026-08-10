from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .config import BASE_SEPOLIA_CHAIN_ID
from .models import CheckResult, VerificationResult
from .policy import looks_like_evm_address


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, frozenset):
        return sorted(value)
    raise TypeError(type(value).__name__)


@dataclass(frozen=True)
class IntentConstraint:
    path: str
    operator: str
    value: Any


@dataclass(frozen=True)
class IntentIRAction:
    protocol: str
    target: str
    function_signature: str
    arguments: tuple[Any, ...] = ()
    native_value: Decimal = Decimal("0")


@dataclass(frozen=True)
class DelegationEnvelope:
    delegation_id: str
    chain_id: str = BASE_SEPOLIA_CHAIN_ID
    allowed_protocols: frozenset[str] = frozenset()
    allowed_targets: frozenset[str] = frozenset()
    allowed_functions: frozenset[str] = frozenset()
    max_native_value: Decimal = Decimal("0")
    expires_at: int | None = None


@dataclass(frozen=True)
class IntentEnvelope:
    intent_id: str
    source_text: str
    action: IntentIRAction
    chain_id: str = BASE_SEPOLIA_CHAIN_ID
    nonce: int = 0
    deadline: int | None = None
    preconditions: tuple[IntentConstraint, ...] = ()
    postconditions: tuple[IntentConstraint, ...] = ()
    invariants: tuple[IntentConstraint, ...] = ()
    source_text_hash: str = ""
    compiler_version: str = "proofpilot-mandate-compiler/1"
    abi_hash: str = ""
    parent_delegation_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def canonical_dict(self) -> dict[str, Any]:
        return asdict(self)

    def commitment(self) -> str:
        encoded = json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=_json_default,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_eip712_typed_data(self, *, verifying_contract: str = "0x" + "0" * 40) -> dict[str, Any]:
        """Return signing-ready typed data. ProofPilot never handles the signing key."""
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "IntentCommitment": [
                    {"name": "intentId", "type": "string"},
                    {"name": "mandateHash", "type": "bytes32"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "deadline", "type": "uint256"},
                ],
            },
            "primaryType": "IntentCommitment",
            "domain": {
                "name": "ProofPilot",
                "version": "1",
                "chainId": int(self.chain_id),
                "verifyingContract": verifying_contract,
            },
            "message": {
                "intentId": self.intent_id,
                "mandateHash": "0x" + self.commitment(),
                "nonce": self.nonce,
                "deadline": self.deadline or 0,
            },
        }


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def abi_hash(abi_json: str) -> str:
    return hashlib.sha256(abi_json.encode("utf-8")).hexdigest()


def delegation_hash(envelope: DelegationEnvelope) -> str:
    encoded = json.dumps(
        asdict(envelope), sort_keys=True, separators=(",", ":"), default=_json_default
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_delegation(
    delegation: DelegationEnvelope,
    intent: IntentEnvelope,
    *,
    now: int | None = None,
) -> VerificationResult:
    now = now if now is not None else int(datetime.now(timezone.utc).timestamp())
    allowed_targets = {value.lower() for value in delegation.allowed_targets}
    checks = (
        CheckResult("delegation_chain", intent.chain_id == delegation.chain_id, "Intent chain is outside delegation."),
        CheckResult("delegation_protocol", not delegation.allowed_protocols or intent.action.protocol in delegation.allowed_protocols, "Intent protocol is outside delegation."),
        CheckResult("delegation_target", not allowed_targets or intent.action.target.lower() in allowed_targets, "Intent target is outside delegation."),
        CheckResult("delegation_function", not delegation.allowed_functions or intent.action.function_signature in delegation.allowed_functions, "Intent function is outside delegation."),
        CheckResult("delegation_native_value", intent.action.native_value <= delegation.max_native_value, "Intent native value exceeds delegation budget."),
        CheckResult("delegation_expiry", delegation.expires_at is None or now <= delegation.expires_at, "Delegation has expired."),
        CheckResult("intent_deadline", intent.deadline is None or now <= intent.deadline, "Intent deadline has expired."),
        CheckResult("intent_target_shape", looks_like_evm_address(intent.action.target), "Intent target is not a valid EVM address."),
    )
    return VerificationResult(all(check.passed for check in checks), checks)

