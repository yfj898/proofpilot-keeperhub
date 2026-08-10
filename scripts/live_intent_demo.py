from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.intent import (  # noqa: E402
    IntentAction,
    IntentMandate,
    ProposedAction,
    StateCondition,
    assure_intent,
    verify_state_conditions,
)
from proofpilot.intent_engine import IntentAssuranceEngine  # noqa: E402
from proofpilot.keeperhub import KeeperHubGate0  # noqa: E402
from proofpilot.mcp import McpHttpClient  # noqa: E402
from proofpilot.proof_bundle import build_intent_proof_bundle  # noqa: E402
from proofpilot.reader import BaseSepoliaReader  # noqa: E402
from proofpilot.verifier import verify_independent_receipt, verify_terminal_execution  # noqa: E402


DEFAULT_TARGET = "0x893a327e3714b2780B28C35FfEcb52AfA0157F15"


STORE_NUMBER_ABI = json.dumps(
    [
        {
            "inputs": [{"internalType": "uint256", "name": "_number", "type": "uint256"}],
            "name": "storeNumber",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        }
    ],
    separators=(",", ":"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ProofPilot Intent Assurance on Base Sepolia.")
    parser.add_argument("--target", default=os.getenv("PROOFPILOT_DEMO_TARGET", DEFAULT_TARGET))
    parser.add_argument("--number", type=int, default=20)
    parser.add_argument("--execute", action="store_true", help="Broadcast only after all pre-write gates pass.")
    args = parser.parse_args()

    api_key = os.getenv("KH_API_KEY", "").strip()
    if not api_key.startswith("kh_"):
        print("KH_API_KEY must be supplied via environment and start with kh_.", file=sys.stderr)
        return 2

    reader = BaseSepoliaReader()
    if reader.chain_id() != "84532":
        print("Independent reader is not connected to Base Sepolia.", file=sys.stderr)
        return 3

    client = McpHttpClient("https://app.keeperhub.com/mcp", bearer_token=api_key)
    client.initialize()
    keeperhub = KeeperHubGate0(client)

    pre_number = reader.get_storage_uint256(args.target, 0)
    mandate = IntentMandate(
        intent_id=f"proofpilot-demo-set-number-{args.number}",
        action=IntentAction.CONTRACT_CALL,
        target=args.target,
        function_signature="storeNumber(uint256)",
        exact_arguments=(args.number,),
        preconditions=(StateCondition("config.number", "eq", pre_number),),
        postconditions=(StateCondition("config.number", "eq", args.number),),
        description=f"Set the ProofPilot demo contract number to exactly {args.number}.",
    )
    proposal = ProposedAction(
        action=IntentAction.CONTRACT_CALL,
        chain_id="84532",
        target=args.target,
        function_signature="storeNumber(uint256)",
        arguments=(args.number,),
    )

    admission = IntentAssuranceEngine(keeperhub).admit_contract_call(
        mandate,
        proposal,
        pre_state={"config": {"number": pre_number}},
        abi=STORE_NUMBER_ABI,
    )
    if not admission.approved:
        print(json.dumps({"approved": False, "error": admission.error}, indent=2))
        return 4

    if not args.execute:
        print(
            json.dumps(
                {
                    "approved": True,
                    "mode": "simulation-only",
                    "pre_state": {"number": pre_number},
                    "simulation": admission.simulation,
                },
                indent=2,
            )
        )
        return 0

    fresh_number = reader.get_storage_uint256(args.target, 0)
    if fresh_number != pre_number:
        print(json.dumps({"approved": False, "error": "stale precondition detected"}, indent=2))
        return 5

    _, submit = keeperhub.execute_contract_call(
        contract_address=args.target,
        function_name="storeNumber",
        function_args=json.dumps([args.number]),
        abi=STORE_NUMBER_ABI,
    )
    execution_id = submit.get("executionId") or submit.get("execution_id") or submit.get("id")
    if not execution_id:
        print(json.dumps({"approved": False, "error": "execution id missing"}, indent=2))
        return 6

    status = keeperhub.poll_status(str(execution_id), max_attempts=18, delay_seconds=2.0)
    terminal = verify_terminal_execution(status)
    tx_hash = status.get("transactionHash") or status.get("transaction_hash")
    receipt = reader.get_transaction_receipt(tx_hash) if tx_hash else None
    independent = verify_independent_receipt(tx_hash, receipt) if tx_hash else None
    post_number = reader.get_storage_uint256(args.target, 0)
    post = verify_state_conditions(
        mandate.postconditions,
        {"config": {"number": post_number}},
        phase="post",
    )
    checks = {
        "intent": assure_intent(mandate, proposal).passed,
        "precondition": True,
        "simulation": bool(admission.simulation_check and admission.simulation_check.passed),
        "keeperhub_receipt": terminal.passed,
        "independent_receipt": bool(independent and independent.passed),
        "postcondition": post.passed,
    }
    proof = build_intent_proof_bundle(
        intent_id=mandate.intent_id,
        chain_id="84532",
        target=args.target,
        mandate={
            "function": mandate.function_signature,
            "arguments": list(mandate.exact_arguments or ()),
            "postconditions": [{"key": c.key, "operator": c.operator, "expected": c.expected} for c in mandate.postconditions],
        },
        proposal={"function": proposal.function_signature, "arguments": list(proposal.arguments)},
        pre_state={"number": pre_number},
        simulation=admission.simulation or {},
        keeperhub_execution={
            "status": status.get("status"),
            "transactionHash": tx_hash,
            "transactionLink": status.get("transactionLink") or status.get("transaction_link"),
        },
        independent_receipt={
            "transactionHash": receipt.get("transactionHash") if receipt else None,
            "status": receipt.get("status") if receipt else None,
            "blockNumber": receipt.get("blockNumber") if receipt else None,
            "blockHash": receipt.get("blockHash") if receipt else None,
        },
        post_state={"number": post_number},
        checks=checks,
    )
    print(json.dumps(proof, indent=2))
    return 0 if proof["verified"] else 7


if __name__ == "__main__":
    raise SystemExit(main())

