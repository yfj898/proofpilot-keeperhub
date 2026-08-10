#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from proofpilot.config import Gate0Config  # noqa: E402
from proofpilot.keeperhub import KeeperHubGate0, verify_terminal_success  # noqa: E402
from proofpilot.mcp import McpError, McpHttpClient  # noqa: E402
from proofpilot.proof import add_stage, new_proof, write_proof  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ProofPilot Gate 0: live KeeperHub MCP -> Base Sepolia preflight."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="After a successful simulation, broadcast one tiny Base Sepolia TESTNET transfer.",
    )
    parser.add_argument(
        "--connectivity-only",
        action="store_true",
        help="Only initialize the public MCP endpoint; no credentials or tool calls required.",
    )
    parser.add_argument(
        "--proof",
        default=str(ROOT / "artifacts" / "gate0" / "latest.json"),
        help="Where to write the local Gate 0 proof JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = Gate0Config.from_env()
    proof = new_proof()
    proof_path = Path(args.proof)

    try:
        client = McpHttpClient(config.endpoint, config.api_key)
        initialized = client.initialize(authenticated=not args.connectivity_only)
        init_result = initialized.payload.get("result", {})
        add_stage(
            proof,
            "mcp_initialize",
            "PASS",
            {
                "http_status": initialized.status,
                "server_info": init_result.get("serverInfo"),
                "protocol_version": init_result.get("protocolVersion"),
                "authentication": init_result.get("authentication"),
            },
        )
        if args.connectivity_only:
            proof["result"] = "CONNECTIVITY_VERIFIED"
            write_proof(proof, proof_path)
            print(json.dumps(proof, indent=2))
            return 0

        errors = config.validate(require_credentials=True)
        if errors:
            add_stage(proof, "local_config", "BLOCKED", {"errors": errors})
            proof["result"] = "BLOCKED_LOCAL_CONFIG"
            write_proof(proof, proof_path)
            print("Gate 0 blocked before authenticated tool calls:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 2

        gate = KeeperHubGate0(client)
        inventory = gate.discover()
        add_stage(
            proof,
            "tools_list",
            "PASS",
            {
                "tool_count": len(inventory.names),
                "required_tools": ["execute_transfer", "get_direct_execution_status"],
                "simulate_advertised": True,
            },
        )

        simulation = gate.simulate_native_transfer(recipient=config.recipient, amount=config.amount)
        add_stage(proof, "simulate_transfer", "PASS", simulation)

        if not args.execute:
            proof["result"] = "SIMULATION_VERIFIED"
            write_proof(proof, proof_path)
            print(json.dumps(proof, indent=2))
            print("\nSimulation passed. Re-run with --execute only for the tiny Base Sepolia TESTNET gate.")
            return 0

        # Safety invariant: execution is reachable only after the simulation stage above passed.
        idempotency_key, broadcast = gate.execute_native_transfer(
            recipient=config.recipient,
            amount=config.amount,
        )
        execution_id = broadcast.get("executionId") or broadcast.get("execution_id")
        if not execution_id:
            raise McpError("Broadcast returned no executionId.", body=broadcast)
        add_stage(
            proof,
            "broadcast",
            "PASS",
            {
                "execution_id": execution_id,
                "idempotency_key": idempotency_key,
                "response": broadcast,
            },
        )

        status = gate.poll_status(str(execution_id))
        verified, verification_errors = verify_terminal_success(status)
        add_stage(
            proof,
            "receipt_verification",
            "PASS" if verified else "FAIL",
            {"status": status, "errors": verification_errors},
        )
        proof["result"] = "VERIFIED" if verified else "FAILED_VERIFICATION"
        write_proof(proof, proof_path)
        print(json.dumps(proof, indent=2))
        return 0 if verified else 4
    except McpError as exc:
        add_stage(
            proof,
            "keeperhub_error",
            "FAIL",
            {"message": str(exc), "http_status": exc.status, "body": exc.body},
        )
        proof["result"] = "FAILED"
        write_proof(proof, proof_path)
        print(f"Gate 0 failed: {exc}", file=sys.stderr)
        if exc.body is not None:
            print(json.dumps(exc.body, indent=2, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

