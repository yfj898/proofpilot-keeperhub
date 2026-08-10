from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.adversarial import GeneratedAttack, generate_repeated_contract_suite  # noqa: E402
from proofpilot.baselines import ProofPilotSemanticBaseline, default_baselines  # noqa: E402
from proofpilot.keeperbench21 import comparison_artifact, evaluate_cases  # noqa: E402
from proofpilot.keeperhub import KeeperHubGate0  # noqa: E402
from proofpilot.mcp import McpHttpClient  # noqa: E402


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
    parser = argparse.ArgumentParser(description="KeeperBench 2.1 repeated adversarial comparison.")
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument(
        "--live-simulations",
        type=int,
        default=0,
        help="Simulation-only live validation of generated wrong-argument cases; never broadcasts.",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    cases = generate_repeated_contract_suite(trials=args.trials, seed=args.seed, target=args.target)
    rows, summaries = evaluate_cases(cases, default_baselines())
    live = _run_live_simulation_subset(cases, args.live_simulations) if args.live_simulations else {}
    artifact = comparison_artifact(
        trials=args.trials,
        seed=args.seed,
        target=args.target,
        rows=rows,
        summaries=summaries,
        live_simulation=live,
    )

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(artifact, indent=2))
    return 0


def _run_live_simulation_subset(cases: list[Any], count: int) -> dict[str, Any]:
    if count <= 0:
        return {}
    api_key = os.getenv("KH_API_KEY", "").strip()
    if not api_key.startswith("kh_"):
        raise SystemExit("--live-simulations requires KH_API_KEY in the environment")

    candidates = [
        case
        for case in cases
        if case.attack
        in {GeneratedAttack.WRONG_ARGUMENT_OFF_BY_ONE, GeneratedAttack.WRONG_ARGUMENT_SCALE}
    ][:count]
    client = McpHttpClient("https://app.keeperhub.com/mcp", bearer_token=api_key)
    client.initialize()
    keeperhub = KeeperHubGate0(client)
    proofpilot = ProofPilotSemanticBaseline()

    results: list[dict[str, Any]] = []
    for case in candidates:
        semantic = proofpilot.evaluate(case)
        argument = case.proposal.arguments[0]
        simulation = keeperhub.simulate_contract_call(
            contract_address=case.proposal.target,
            function_name="storeNumber",
            function_args=json.dumps([argument]),
            abi=STORE_NUMBER_ABI,
        )
        simulation_passed = (
            simulation.get("success") is True and simulation.get("wouldRevert") is False
        )
        results.append(
            {
                "case_id": case.case_id,
                "attack": case.attack.value,
                "generated_argument": argument,
                "proofpilot_approved": semantic.approved,
                "keeperhub_simulation_passed": simulation_passed,
                "wouldRevert": simulation.get("wouldRevert"),
            }
        )

    unsafe_simulation_approved = sum(
        row["keeperhub_simulation_passed"] and not row["proofpilot_approved"] for row in results
    )
    return {
        "mode": "simulation_only_no_broadcast",
        "sample_count": len(results),
        "keeperhub_simulation_unsafe_approved": unsafe_simulation_approved,
        "keeperhub_simulation_unsafe_approval_rate": (
            unsafe_simulation_approved / len(results) if results else 0.0
        ),
        "proofpilot_unsafe_approved": sum(row["proofpilot_approved"] for row in results),
        "cases": results,
    }


if __name__ == "__main__":
    raise SystemExit(main())
