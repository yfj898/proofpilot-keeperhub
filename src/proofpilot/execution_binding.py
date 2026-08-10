from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from .intent import ProposedAction


def canonical_contract_call_payload(
    proposal: ProposedAction,
    *,
    abi: str,
) -> dict[str, Any]:
    """Build the single canonical KeeperHub contract-call payload used end-to-end."""

    return {
        "chain_id": str(proposal.chain_id),
        "contract_address": proposal.target.lower(),
        "function_signature": proposal.function_signature,
        "function_name": proposal.function_signature.split("(", 1)[0],
        "function_args": json.dumps(list(proposal.arguments), separators=(",", ":")),
        "value": format(proposal.native_value, "f"),
        "abi": abi,
        "abi_sha256": hashlib.sha256(abi.encode("utf-8")).hexdigest() if abi else "",
    }


def execution_payload_sha256(payload: dict[str, Any]) -> str:
    """Commit to transaction semantics without duplicating the full ABI in the digest input."""

    serializable = {key: value for key, value in payload.items() if key != "abi"}
    encoded = json.dumps(
        serializable,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def payload_native_value_wei(payload: dict[str, Any]) -> int | None:
    try:
        value = Decimal(str(payload.get("value", "0"))) * (Decimal(10) ** 18)
    except Exception:
        return None
    if value != value.to_integral_value() or value < 0:
        return None
    return int(value)
