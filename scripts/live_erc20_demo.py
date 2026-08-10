from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.erc20_adapter import ERC20_TRANSFER_ABI, ERC20TransferAdapter  # noqa: E402
from proofpilot.intent import verify_state_snapshot_fresh  # noqa: E402
from proofpilot.intent_engine import IntentAssuranceEngine  # noqa: E402
from proofpilot.keeperhub import KeeperHubGate0  # noqa: E402
from proofpilot.mcp import McpHttpClient  # noqa: E402
from proofpilot.reader import BaseSepoliaReader  # noqa: E402
from proofpilot.verifier import verify_independent_receipt, verify_terminal_execution  # noqa: E402


DEFAULT_TOKEN = "0x60c8a606b2114337b4301bd55b48e33c9d86643e"
DEFAULT_RECIPIENT = "0x1111111111111111111111111111111111111111"


def _integration_address(value: object) -> str | None:
    if isinstance(value, dict):
        for item in value.values():
            found = _integration_address(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _integration_address(item)
            if found:
                return found
    elif isinstance(value, str) and re.fullmatch(r"0x[a-fA-F0-9]{40}", value):
        return value
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ProofPilot ERC-20 outcome demo on Base Sepolia.")
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--recipient", default=DEFAULT_RECIPIENT)
    parser.add_argument("--raw-amount", type=int, default=1_000_000)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    api_key = os.getenv("KH_API_KEY", "").strip()
    if not api_key.startswith("kh_"):
        print("KH_API_KEY is required in the environment.", file=sys.stderr)
        return 2

    reader = BaseSepoliaReader(
        rpc_url="https://base-sepolia-rpc.publicnode.com",
        timeout=5,
        prefer_curl=True,
        fallback_rpc_urls=("https://84532.rpc.thirdweb.com", "https://sepolia.base.org"),
    )
    if reader.chain_id() != "84532":
        print("Independent read layer is not Base Sepolia.", file=sys.stderr)
        return 3

    client = McpHttpClient("https://app.keeperhub.com/mcp", bearer_token=api_key)
    client.initialize()
    integrations = client.call_tool("list_integrations", {})
    sender = _integration_address(integrations)
    if not sender:
        print("No EVM integration address found.", file=sys.stderr)
        return 4

    keeperhub = KeeperHubGate0(client)
    adapter = ERC20TransferAdapter(args.token, sender, args.recipient, args.raw_amount)
    mandate = adapter.mandate(intent_id="proofpilot-erc20-live")
    proposal = adapter.proposal(mandate)
    pre = adapter.read_state(reader)
    admission = IntentAssuranceEngine(keeperhub).admit_contract_call(
        mandate, proposal, pre_state={}, abi=ERC20_TRANSFER_ABI
    )
    if not admission.approved:
        print(json.dumps({"approved": False, "error": admission.error}, indent=2))
        return 5

    if not args.execute:
        print(
            json.dumps(
                {
                    "approved": True,
                    "mode": "simulation-only",
                    "pre_state": pre,
                    "simulation": admission.simulation,
                },
                indent=2,
            )
        )
        return 0

    fresh = adapter.read_state(reader)
    freshness = verify_state_snapshot_fresh(pre, fresh, phase="erc20_fresh")
    if not freshness.passed:
        print(json.dumps({"approved": False, "error": "; ".join(freshness.reasons)}, indent=2))
        return 6

    _, submit = keeperhub.execute_contract_call(
        contract_address=args.token,
        function_name="transfer",
        function_args=json.dumps([args.recipient, args.raw_amount]),
        abi=ERC20_TRANSFER_ABI,
    )
    execution_id = submit.get("executionId") or submit.get("execution_id") or submit.get("id")
    status = submit
    if str(status.get("status", "")).lower() not in {"completed", "failed"}:
        if not execution_id:
            print(json.dumps({"approved": False, "error": "execution id missing"}, indent=2))
            return 7
        status = keeperhub.poll_status(str(execution_id), max_attempts=15, delay_seconds=1.0)

    terminal = verify_terminal_execution(status)
    tx_hash = status.get("transactionHash") or status.get("transaction_hash")
    receipt = reader.get_transaction_receipt(tx_hash) if tx_hash else None
    independent = verify_independent_receipt(tx_hash, receipt) if tx_hash else None
    post = adapter.read_state(reader)
    outcome = adapter.verify_outcome(mandate, pre, post)
    verified = terminal.passed and bool(independent and independent.passed) and outcome.passed
    print(
        json.dumps(
            {
                "verified": verified,
                "transaction_hash": tx_hash,
                "pre_state": pre,
                "post_state": post,
                "sender_delta": pre["sender"] - post["sender"],
                "recipient_delta": post["recipient"] - pre["recipient"],
                "checks": {
                    "keeperhub_terminal": terminal.passed,
                    "independent_receipt": bool(independent and independent.passed),
                    "outcome": outcome.passed,
                },
            },
            indent=2,
        )
    )
    return 0 if verified else 8


if __name__ == "__main__":
    raise SystemExit(main())

