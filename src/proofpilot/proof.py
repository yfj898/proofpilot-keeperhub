from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def new_proof() -> dict[str, Any]:
    return {
        "schema": "proofpilot.gate0.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "network": {"name": "Base Sepolia", "chain_id": "84532"},
        "stages": [],
        "result": "INCOMPLETE",
    }


def add_stage(proof: dict[str, Any], name: str, status: str, data: Any = None) -> None:
    stage: dict[str, Any] = {
        "name": name,
        "status": status,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if data is not None:
        stage["data"] = data
    proof["stages"].append(stage)


def write_proof(proof: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

