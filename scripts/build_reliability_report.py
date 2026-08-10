from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.aave_adapter import (  # noqa: E402
    AAVE_BASE_SEPOLIA_POOL,
    AAVE_SET_USER_EMODE_ABI,
    AaveEModeAdapter,
)
from proofpilot.intent import (  # noqa: E402
    IntentAction,
    IntentMandate,
    ProposedAction,
    StateCondition,
    assure_intent,
    verify_state_conditions,
    verify_state_snapshot_fresh,
)
from proofpilot.intent_engine import IntentAssuranceEngine  # noqa: E402
from proofpilot.mcp import McpError  # noqa: E402
from proofpilot.proof_bundle import (  # noqa: E402
    build_execution_trace_v2,
    verify_execution_trace_v2,
)
from proofpilot.replay import IntentReplayGuard  # noqa: E402
from proofpilot.verifier import (  # noqa: E402
    verify_independent_receipt,
    verify_simulation,
    verify_terminal_execution,
)


ACCOUNT = "0x1111111111111111111111111111111111111111"
OTHER_TARGET = "0x2222222222222222222222222222222222222222"


class FailingContractSimulator:
    def simulate_contract_call(self, **_: Any) -> dict[str, Any]:
        raise McpError("synthetic KeeperHub tool failure", status=503)


def _base_mandate() -> IntentMandate:
    return AaveEModeAdapter(ACCOUNT, 1).mandate(intent_id="reliability-aave-emode")


def _base_proposal() -> ProposedAction:
    mandate = _base_mandate()
    return ProposedAction(
        action=IntentAction.CONTRACT_CALL,
        chain_id=mandate.chain_id,
        target=mandate.target,
        function_signature=mandate.function_signature,
        arguments=mandate.exact_arguments or (),
        native_value=Decimal("0"),
    )


def _case(
    case_id: str,
    category: str,
    expected: str,
    observed: str,
    passed: bool,
    *,
    unsafe_broadcast: bool = False,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "category": category,
        "expected_behavior": expected,
        "observed_behavior": observed,
        "passed": bool(passed),
        "unsafe_broadcast": bool(unsafe_broadcast),
        "evidence": evidence or {},
    }


def _failed_names(result: Any) -> list[str]:
    return [check.name for check in getattr(result, "checks", ()) if not check.passed]


def build_cases() -> list[dict[str, Any]]:
    mandate = _base_mandate()
    base = _base_proposal()
    cases: list[dict[str, Any]] = []

    mutations: list[tuple[str, str, ProposedAction, str]] = [
        (
            "wrong_chain",
            "semantic_admission",
            replace(base, chain_id="1"),
            "intent_chain",
        ),
        (
            "wrong_target",
            "semantic_admission",
            replace(base, target=OTHER_TARGET),
            "intent_target",
        ),
        (
            "wrong_function",
            "semantic_admission",
            replace(base, function_signature="setUserUseReserveAsCollateral(address,bool)"),
            "intent_function",
        ),
        (
            "wrong_arguments",
            "semantic_admission",
            replace(base, arguments=(0,)),
            "intent_arguments",
        ),
        (
            "wrong_native_value",
            "semantic_admission",
            replace(base, native_value=Decimal("0.0001")),
            "intent_native_value",
        ),
    ]
    for case_id, category, proposal, expected_check in mutations:
        decision = assure_intent(mandate, proposal)
        failed = _failed_names(decision)
        cases.append(
            _case(
                case_id,
                category,
                "Reject before any broadcast.",
                f"passed={decision.passed}; failed_checks={failed}",
                (not decision.passed) and expected_check in failed,
                evidence={"failed_checks": failed},
            )
        )

    freshness = verify_state_snapshot_fresh(
        {"aave": {"user_emode": 0}},
        {"aave": {"user_emode": 1}},
        phase="prebroadcast_fresh",
    )
    cases.append(
        _case(
            "stale_state",
            "state_freshness",
            "Fail closed when pre-broadcast state differs from the admitted snapshot.",
            f"passed={freshness.passed}; failed_checks={_failed_names(freshness)}",
            not freshness.passed,
            evidence={"failed_checks": _failed_names(freshness)},
        )
    )

    simulation = {"success": True, "wouldRevert": True, "status": "simulated"}
    simulation_check = verify_simulation(simulation)
    cases.append(
        _case(
            "simulation_revert",
            "keeperhub_preflight",
            "Do not broadcast a transaction that simulation says would revert.",
            f"passed={simulation_check.passed}; failed_checks={_failed_names(simulation_check)}",
            not simulation_check.passed,
            evidence={"simulation": simulation, "failed_checks": _failed_names(simulation_check)},
        )
    )

    mcp_admission = IntentAssuranceEngine(FailingContractSimulator()).admit_contract_call(
        mandate,
        base,
        pre_state={"aave": {"user_emode": 0}},
        abi=AAVE_SET_USER_EMODE_ABI,
    )
    cases.append(
        _case(
            "mcp_tool_error",
            "keeperhub_preflight",
            "KeeperHub/MCP tool errors fail closed and do not cross the write boundary.",
            f"approved={mcp_admission.approved}; error={mcp_admission.error}",
            not mcp_admission.approved,
            evidence={"error": mcp_admission.error},
        )
    )

    replay_guard = IntentReplayGuard()
    replay_guard.consume(mandate, base)
    replay = replay_guard.check(mandate, base)
    cases.append(
        _case(
            "duplicate_replay",
            "replay_containment",
            "A consumed semantic intent cannot be consumed a second time.",
            f"passed={replay.passed}; failed_checks={_failed_names(replay)}",
            not replay.passed,
            evidence={"failed_checks": _failed_names(replay)},
        )
    )

    uncertain_status = {"status": "pending"}
    terminal = verify_terminal_execution(uncertain_status)
    cases.append(
        _case(
            "uncertain_execution_status",
            "execution_verification",
            "Never claim execution success without a completed status and receipt evidence.",
            f"passed={terminal.passed}; failed_checks={_failed_names(terminal)}",
            not terminal.passed,
            evidence={"failed_checks": _failed_names(terminal)},
        )
    )

    tx_hash = "0x" + "a" * 64
    failed_receipt = verify_independent_receipt(
        tx_hash,
        {
            "transactionHash": tx_hash,
            "status": "0x0",
            "blockHash": "0x" + "b" * 64,
            "blockNumber": "0x1",
        },
    )
    cases.append(
        _case(
            "receipt_failure",
            "independent_verification",
            "A failed independent EVM receipt prevents VERIFIED status.",
            f"passed={failed_receipt.passed}; failed_checks={_failed_names(failed_receipt)}",
            not failed_receipt.passed,
            evidence={"failed_checks": _failed_names(failed_receipt)},
        )
    )

    post_mandate = IntentMandate(
        intent_id="postcondition-test",
        action=IntentAction.CONTRACT_CALL,
        target=AAVE_BASE_SEPOLIA_POOL,
        function_signature="setUserEMode(uint8)",
        exact_arguments=(1,),
        exact_native_value=Decimal("0"),
        postconditions=(StateCondition("aave.user_emode", "eq", 1),),
    )
    post = verify_state_conditions(
        post_mandate.postconditions,
        {"aave": {"user_emode": 0}},
        phase="post",
    )
    cases.append(
        _case(
            "postcondition_mismatch",
            "independent_verification",
            "A successful-looking execution cannot be VERIFIED when the intended state is absent.",
            f"passed={post.passed}; failed_checks={_failed_names(post)}",
            not post.passed,
            evidence={"failed_checks": _failed_names(post)},
        )
    )

    trace = build_execution_trace_v2(
        user_intent="Set Aave E-Mode to 1",
        intent_ir={},
        intent_commitment="a" * 64,
        proposal={"function_signature": "setUserEMode(uint8)", "arguments": [0]},
        intent_assurance={"passed": False, "checks": []},
        pre_state={"aave": {"user_emode": 0}},
        keeperhub_simulation={"success": True, "wouldRevert": False},
        semantic_deviations=["wrong_emode_category"],
        final_status="BLOCKED",
        broadcast_attempted=False,
    )
    tampered = deepcopy(trace)
    tampered["proposal"]["action"]["arguments"] = [1]
    tamper_rejected = not verify_execution_trace_v2(tampered)
    cases.append(
        _case(
            "tampered_trace",
            "evidence_integrity",
            "Any post-hoc mutation invalidates the trace digest.",
            f"tampered_trace_verified={not tamper_rejected}",
            tamper_rejected,
        )
    )

    live_verified_path = ROOT / "artifacts/demo/proofpilot-safe-live-validation-trace-v2.json"
    live_blocked_path = ROOT / "artifacts/demo/proofpilot-attack-validation-trace-v2.json"
    for case_id, category, path, expected_status in (
        (
            "live_verified_execution_trace",
            "live_evidence",
            live_verified_path,
            "VERIFIED",
        ),
        (
            "live_simulation_valid_attack_blocked",
            "live_evidence",
            live_blocked_path,
            "BLOCKED",
        ),
    ):
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            integrity = verify_execution_trace_v2(loaded)
            status_ok = loaded.get("final_status") == expected_status
            if expected_status == "BLOCKED":
                sim = loaded.get("keeperhub", {}).get("simulation", {})
                specific = (
                    sim.get("success") is True
                    and sim.get("wouldRevert") is False
                    and loaded.get("broadcast_attempted") is False
                )
            else:
                specific = loaded.get("broadcast_attempted") is True
            passed = integrity and status_ok and specific
            observed = (
                f"integrity={integrity}; final_status={loaded.get('final_status')}; "
                f"broadcast_attempted={loaded.get('broadcast_attempted')}"
            )
            evidence = {"artifact": str(path.relative_to(ROOT)), "trace_sha256": loaded.get("sha256")}
        else:
            passed = False
            observed = "required live trace artifact is missing"
            evidence = {"artifact": str(path.relative_to(ROOT))}
        cases.append(
            _case(
                case_id,
                category,
                f"Preserved live trace remains integrity-valid with final status {expected_status}.",
                observed,
                passed,
                unsafe_broadcast=False,
                evidence=evidence,
            )
        )

    return cases


def build_report() -> dict[str, Any]:
    cases = build_cases()
    passed = sum(1 for case in cases if case["passed"])
    unsafe = sum(1 for case in cases if case["unsafe_broadcast"])
    return {
        "schema": "proofpilot.reliability-report.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "testnet_only": True,
        "definition": (
            "Competition-facing fail-closed reliability matrix. Deterministic cases exercise "
            "semantic admission, preflight, replay, execution verification, independent outcome "
            "verification, and evidence integrity; live rows reference preserved Base Sepolia traces."
        ),
        "summary": {
            "total_cases": len(cases),
            "passed_cases": passed,
            "failed_cases": len(cases) - passed,
            "unsafe_broadcasts": unsafe,
        },
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the ProofPilot competition reliability report.")
    parser.add_argument(
        "--artifact",
        default=str(ROOT / "artifacts/reliability/reliability-report.json"),
    )
    args = parser.parse_args(argv)
    report = build_report()
    path = Path(args.artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    summary = report["summary"]
    print(f"ARTIFACT={path}")
    print(
        "cases=", summary["total_cases"],
        "passed=", summary["passed_cases"],
        "failed=", summary["failed_cases"],
        "unsafe_broadcasts=", summary["unsafe_broadcasts"],
    )
    return 0 if summary["failed_cases"] == 0 and summary["unsafe_broadcasts"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
