from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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
from proofpilot.keeperhub import KeeperHubGate0  # noqa: E402
from proofpilot.live_keeperbench import (  # noqa: E402
    LIVE_SCENARIO_NAMES,
    LiveBenchResult,
    summarize_live_results,
)
from proofpilot.mcp import McpHttpClient  # noqa: E402
from proofpilot.proof_bundle import (  # noqa: E402
    build_intent_proof_bundle,
    verify_intent_proof_bundle,
)
from proofpilot.reader import BaseSepoliaReader  # noqa: E402
from proofpilot.replay import IntentReplayGuard  # noqa: E402
from proofpilot.verifier import (  # noqa: E402
    verify_independent_receipt,
    verify_terminal_execution,
)


DEFAULT_TARGET = "0x893a327e3714b2780B28C35FfEcb52AfA0157F15"
DEFAULT_WRONG_TARGET = "0x1516EE7E3c0bca2f2c3952d6173269da7fe40f2D"
KNOWN_VERIFIED_TX = "0x5cfed9c7271144fd4266ce0dbee90fd91384694cd60791a08078a3f206775569"
READ_RPC_CANDIDATES = (
    "https://84532.rpc.thirdweb.com",
    "https://base-sepolia-rpc.publicnode.com",
    "https://sepolia.base.org",
)

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


@dataclass
class LiveContext:
    reader: BaseSepoliaReader
    keeperhub: KeeperHubGate0
    engine: IntentAssuranceEngine
    replay: IntentReplayGuard
    target: str
    wrong_target: str
    run_id: str
    last_verified_proof: dict[str, Any] | None = None
    last_verified_tx_hash: str = ""


def _mandate(ctx: LiveContext, *, intent_suffix: str, before: int, goal: int) -> IntentMandate:
    return IntentMandate(
        intent_id=f"keeperbench-live-{ctx.run_id}-{intent_suffix}",
        action=IntentAction.CONTRACT_CALL,
        target=ctx.target,
        function_signature="storeNumber(uint256)",
        exact_arguments=(goal,),
        preconditions=(StateCondition("config.number", "eq", before),),
        postconditions=(StateCondition("config.number", "eq", goal),),
        description=f"Set the isolated Base Sepolia demo state from {before} to exactly {goal}.",
    )


def _proposal(ctx: LiveContext, goal: int) -> ProposedAction:
    return ProposedAction(
        action=IntentAction.CONTRACT_CALL,
        chain_id="84532",
        target=ctx.target,
        function_signature="storeNumber(uint256)",
        arguments=(goal,),
    )


def _execution_id(payload: dict[str, Any]) -> str:
    value = payload.get("executionId") or payload.get("execution_id") or payload.get("id")
    return str(value or "")


def _tx_hash(status: dict[str, Any]) -> str:
    value = status.get("transactionHash") or status.get("transaction_hash")
    return str(value or "")


def _wait_number(reader: BaseSepoliaReader, target: str, expected: int, *, attempts: int = 16) -> int:
    observed = reader.get_storage_uint256(target, 0)
    for _ in range(attempts - 1):
        if observed == expected:
            return observed
        time.sleep(0.5)
        observed = reader.get_storage_uint256(target, 0)
    return observed


def _execute_number(
    ctx: LiveContext,
    value: int,
    *,
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], str]:
    _, submit = ctx.keeperhub.execute_contract_call(
        contract_address=ctx.target,
        function_name="storeNumber",
        function_args=json.dumps([value]),
        abi=STORE_NUMBER_ABI,
        idempotency_key=idempotency_key,
    )
    execution_id = _execution_id(submit)
    if not execution_id:
        raise RuntimeError(f"KeeperHub did not return execution id: {submit}")
    status = ctx.keeperhub.poll_status(execution_id, max_attempts=20, delay_seconds=0.5)
    return status, execution_id


def _adversary_write(ctx: LiveContext, value: int) -> tuple[dict[str, Any], str]:
    simulation = ctx.keeperhub.simulate_contract_call(
        contract_address=ctx.target,
        function_name="storeNumber",
        function_args=json.dumps([value]),
        abi=STORE_NUMBER_ABI,
    )
    if simulation.get("success") is not True or simulation.get("wouldRevert") is True:
        raise RuntimeError(f"Adversary injection simulation failed: {simulation}")
    status, execution_id = _execute_number(ctx, value)
    if _wait_number(ctx.reader, ctx.target, value) != value:
        raise RuntimeError("Adversary state mutation was not independently observed.")
    return status, execution_id


def _verified_execution(
    ctx: LiveContext,
    mandate: IntentMandate,
    proposal: ProposedAction,
    *,
    before: int,
) -> tuple[bool, dict[str, Any], dict[str, Any] | None, int]:
    admission = ctx.engine.admit_contract_call(
        mandate,
        proposal,
        pre_state={"config": {"number": before}},
        abi=STORE_NUMBER_ABI,
    )
    if not admission.approved:
        return False, {"admission_error": admission.error}, None, before

    fresh = ctx.reader.get_storage_uint256(ctx.target, 0)
    freshness = verify_state_snapshot_fresh(
        {"config": {"number": before}},
        {"config": {"number": fresh}},
        phase="prewrite",
    )
    if not freshness.passed:
        return False, {"freshness": list(freshness.reasons)}, None, fresh

    status, _ = _execute_number(ctx, int(proposal.arguments[0]))
    tx_hash = _tx_hash(status)
    receipt = ctx.reader.get_transaction_receipt(tx_hash) if tx_hash else None
    terminal = verify_terminal_execution(status)
    independent = verify_independent_receipt(tx_hash, receipt) if tx_hash else None
    post_number = _wait_number(ctx.reader, ctx.target, int(proposal.arguments[0]))
    post = verify_state_conditions(
        mandate.postconditions,
        {"config": {"number": post_number}},
        phase="post",
    )
    checks = {
        "intent": assure_intent(mandate, proposal).passed,
        "freshness": freshness.passed,
        "keeperhub_receipt": terminal.passed,
        "independent_receipt": bool(independent and independent.passed),
        "postcondition": post.passed,
    }
    proof = build_intent_proof_bundle(
        intent_id=mandate.intent_id,
        chain_id="84532",
        target=ctx.target,
        mandate={"function": mandate.function_signature, "arguments": list(mandate.exact_arguments or ())},
        proposal={"function": proposal.function_signature, "arguments": list(proposal.arguments)},
        pre_state={"number": before},
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
    if proof["verified"]:
        ctx.last_verified_proof = proof
        ctx.last_verified_tx_hash = tx_hash
    return bool(proof["verified"]), {"checks": checks, "tx_hash": tx_hash}, proof, post_number


def _semantic_block_result(
    name: str,
    mandate: IntentMandate,
    proposal: ProposedAction,
) -> LiveBenchResult:
    decision = assure_intent(mandate, proposal)
    return LiveBenchResult(
        name=name,
        category="semantic_prewrite",
        expectation="reject_before_keeperhub_write",
        correct=not decision.passed,
        primary_write_calls=0,
        evidence={"approved": decision.passed, "reasons": list(decision.reasons)},
    )


def _case_safe_live_control(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    goal = before + 1
    mandate = _mandate(ctx, intent_suffix="safe", before=before, goal=goal)
    proposal = _proposal(ctx, goal)
    verified, evidence, _, post = _verified_execution(ctx, mandate, proposal, before=before)
    tx_hash = str(evidence.get("tx_hash", ""))
    return LiveBenchResult(
        "safe_live_control",
        "control",
        "execute_and_verify",
        verified and post == goal,
        primary_write_calls=1 if tx_hash else 0,
        transaction_hashes=(tx_hash,) if tx_hash else (),
        evidence={**evidence, "before": before, "goal": goal, "post": post},
    )


def _case_wrong_chain(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    mandate = _mandate(ctx, intent_suffix="wrong-chain", before=before, goal=before + 1)
    return _semantic_block_result(
        "wrong_chain", mandate, replace(_proposal(ctx, before + 1), chain_id="1")
    )


def _case_wrong_target(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    mandate = _mandate(ctx, intent_suffix="wrong-target", before=before, goal=before + 1)
    return _semantic_block_result(
        "wrong_target", mandate, replace(_proposal(ctx, before + 1), target=ctx.wrong_target)
    )


def _case_wrong_function(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    mandate = _mandate(ctx, intent_suffix="wrong-function", before=before, goal=before + 1)
    return _semantic_block_result(
        "wrong_function",
        mandate,
        replace(_proposal(ctx, before + 1), function_signature="getStoredNumber()", arguments=()),
    )


def _case_wrong_arguments(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    goal = before + 1
    mandate = _mandate(ctx, intent_suffix="wrong-args", before=before, goal=goal)
    return _semantic_block_result(
        "wrong_arguments", mandate, replace(_proposal(ctx, goal), arguments=(goal + 100,))
    )


def _case_malformed_target(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    goal = before + 1
    mandate = _mandate(ctx, intent_suffix="malformed", before=before, goal=goal)
    return _semantic_block_result(
        "malformed_target", mandate, replace(_proposal(ctx, goal), target="0x1234")
    )


def _case_stale_snapshot_before_simulation(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    adversary_status, _ = _adversary_write(ctx, before + 1)
    observed = ctx.reader.get_storage_uint256(ctx.target, 0)
    freshness = verify_state_snapshot_fresh(
        {"config": {"number": before}},
        {"config": {"number": observed}},
        phase="before_simulation",
    )
    adv_tx = _tx_hash(adversary_status)
    return LiveBenchResult(
        "stale_snapshot_before_simulation",
        "freshness_prewrite",
        "detect_state_change_before_simulation",
        not freshness.passed and observed != before,
        primary_write_calls=0,
        adversary_write_calls=1,
        transaction_hashes=(adv_tx,) if adv_tx else (),
        evidence={"snapshot": before, "observed": observed, "reasons": list(freshness.reasons)},
    )


def _case_simulation_execution_race(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    goal = before + 2
    mandate = _mandate(ctx, intent_suffix="sim-race", before=before, goal=goal)
    proposal = _proposal(ctx, goal)
    admission = ctx.engine.admit_contract_call(
        mandate,
        proposal,
        pre_state={"config": {"number": before}},
        abi=STORE_NUMBER_ABI,
    )
    adversary_status, _ = _adversary_write(ctx, before + 1)
    observed = ctx.reader.get_storage_uint256(ctx.target, 0)
    freshness = verify_state_snapshot_fresh(
        {"config": {"number": before}},
        {"config": {"number": observed}},
        phase="prewrite",
    )
    adv_tx = _tx_hash(adversary_status)
    return LiveBenchResult(
        "simulation_execution_race",
        "freshness_prewrite",
        "simulation_passes_but_stale_state_blocks_write",
        admission.approved and not freshness.passed and observed == before + 1,
        primary_write_calls=0,
        adversary_write_calls=1,
        transaction_hashes=(adv_tx,) if adv_tx else (),
        evidence={
            "simulation_approved": admission.approved,
            "snapshot": before,
            "observed_after_adversary": observed,
            "freshness_reasons": list(freshness.reasons),
        },
    )


def _case_duplicate_semantic_intent(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    goal = before + 1
    mandate = _mandate(ctx, intent_suffix="semantic-replay", before=before, goal=goal)
    proposal = _proposal(ctx, goal)
    first_check = ctx.replay.check(mandate, proposal)
    verified, evidence, _, post = _verified_execution(ctx, mandate, proposal, before=before)
    if verified:
        ctx.replay.consume(mandate, proposal)
    replay_check = ctx.replay.check(mandate, proposal)
    tx_hash = str(evidence.get("tx_hash", ""))
    return LiveBenchResult(
        "duplicate_semantic_intent",
        "semantic_replay",
        "first_execution_allowed_second_semantic_intent_blocked",
        first_check.passed and verified and not replay_check.passed and post == goal,
        primary_write_calls=1 if tx_hash else 0,
        transaction_hashes=(tx_hash,) if tx_hash else (),
        evidence={
            "first_guard_passed": first_check.passed,
            "first_verified": verified,
            "replay_guard_passed": replay_check.passed,
            "replay_reasons": list(replay_check.reasons),
        },
    )


def _case_keeperhub_idempotency_replay(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    goal = before + 1
    mandate = _mandate(ctx, intent_suffix="transport-idempotency", before=before, goal=goal)
    proposal = _proposal(ctx, goal)
    admission = ctx.engine.admit_contract_call(
        mandate,
        proposal,
        pre_state={"config": {"number": before}},
        abi=STORE_NUMBER_ABI,
    )
    fresh = ctx.reader.get_storage_uint256(ctx.target, 0)
    freshness = verify_state_snapshot_fresh(
        {"config": {"number": before}}, {"config": {"number": fresh}}, phase="prewrite"
    )
    if not admission.approved or not freshness.passed:
        return LiveBenchResult(
            "keeperhub_idempotency_replay",
            "transport_idempotency",
            "same_idempotency_key_returns_same_execution",
            False,
            evidence={"admission": admission.approved, "freshness": freshness.passed},
        )

    key = f"proofpilot-bench-idem-{ctx.run_id}"
    status1, execution_id1 = _execute_number(ctx, goal, idempotency_key=key)
    tx1 = _tx_hash(status1)
    _, submit2 = ctx.keeperhub.execute_contract_call(
        contract_address=ctx.target,
        function_name="storeNumber",
        function_args=json.dumps([goal]),
        abi=STORE_NUMBER_ABI,
        idempotency_key=key,
    )
    execution_id2 = _execution_id(submit2)
    status2 = (
        ctx.keeperhub.poll_status(execution_id2, max_attempts=8, delay_seconds=1.0)
        if execution_id2
        else submit2
    )
    tx2 = _tx_hash(status2) or _tx_hash(submit2)
    post = _wait_number(ctx.reader, ctx.target, goal)
    same_execution = bool(execution_id1 and execution_id2 and execution_id1 == execution_id2)
    same_tx = bool(tx1 and tx2 and tx1.lower() == tx2.lower())
    correct = (same_execution or same_tx) and post == goal
    txs = tuple(tx for tx in (tx1, tx2) if tx)
    return LiveBenchResult(
        "keeperhub_idempotency_replay",
        "transport_idempotency",
        "same_idempotency_key_returns_same_execution",
        correct,
        primary_write_calls=2,
        transaction_hashes=txs,
        evidence={
            "execution_id_1": execution_id1,
            "execution_id_2": execution_id2,
            "same_execution": same_execution,
            "same_tx": same_tx,
            "post": post,
        },
    )


def _case_post_state_drift(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    goal = before + 1
    mandate = _mandate(ctx, intent_suffix="post-drift", before=before, goal=goal)
    proposal = _proposal(ctx, goal)
    verified, evidence, _, immediate_post = _verified_execution(ctx, mandate, proposal, before=before)
    primary_tx = str(evidence.get("tx_hash", ""))
    adversary_status, _ = _adversary_write(ctx, goal + 1)
    final_number = ctx.reader.get_storage_uint256(ctx.target, 0)
    final_post = verify_state_conditions(
        mandate.postconditions,
        {"config": {"number": final_number}},
        phase="final_post",
    )
    adversary_tx = _tx_hash(adversary_status)
    return LiveBenchResult(
        "post_state_drift",
        "postwrite_drift",
        "detect_intent_no_longer_holds_after_external_state_change",
        verified and immediate_post == goal and not final_post.passed and final_number == goal + 1,
        primary_write_calls=1 if primary_tx else 0,
        adversary_write_calls=1,
        transaction_hashes=tuple(tx for tx in (primary_tx, adversary_tx) if tx),
        evidence={
            "immediate_verified": verified,
            "immediate_post": immediate_post,
            "final_number": final_number,
            "final_reasons": list(final_post.reasons),
        },
    )


def _case_receipt_hash_tampering(ctx: LiveContext) -> LiveBenchResult:
    tx_hash = ctx.last_verified_tx_hash or KNOWN_VERIFIED_TX
    receipt = ctx.reader.get_transaction_receipt(tx_hash)
    wrong_hash = "0x" + "00" * 32
    decision = verify_independent_receipt(wrong_hash, receipt)
    return LiveBenchResult(
        "receipt_hash_tampering",
        "evidence_tamper",
        "independent_receipt_rejects_mismatched_hash",
        not decision.passed,
        evidence={"source_tx": tx_hash, "tampered_tx": wrong_hash, "reasons": list(decision.reasons)},
    )


def _case_proof_bundle_tampering(ctx: LiveContext) -> LiveBenchResult:
    source = ctx.last_verified_proof or build_intent_proof_bundle(
        intent_id="keeperbench-tamper-fixture",
        chain_id="84532",
        target=ctx.target,
        mandate={"function": "storeNumber(uint256)", "arguments": [20]},
        proposal={"function": "storeNumber(uint256)", "arguments": [20]},
        pre_state={"number": 0},
        simulation={"success": True, "status": "simulated", "wouldRevert": False},
        keeperhub_execution={"status": "completed", "transactionHash": KNOWN_VERIFIED_TX},
        independent_receipt={"transactionHash": KNOWN_VERIFIED_TX, "status": "0x1"},
        post_state={"number": 20},
        checks={"intent": True, "postcondition": True},
        created_at="2026-08-08T00:00:00+00:00",
    )
    original_ok = verify_intent_proof_bundle(source)
    tampered = copy.deepcopy(source)
    tampered.setdefault("post_state", {})["number"] = int(
        tampered.get("post_state", {}).get("number", 0)
    ) + 999
    tampered_ok = verify_intent_proof_bundle(tampered)
    return LiveBenchResult(
        "proof_bundle_tampering",
        "evidence_tamper",
        "proof_digest_rejects_modified_post_state",
        original_ok and not tampered_ok,
        evidence={"original_digest_valid": original_ok, "tampered_digest_valid": tampered_ok},
    )


def _case_semantic_recovery_after_drift(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    goal = before + 2
    mandate = _mandate(ctx, intent_suffix="recovery-original", before=before, goal=goal)
    proposal = _proposal(ctx, goal)
    admission = ctx.engine.admit_contract_call(
        mandate,
        proposal,
        pre_state={"config": {"number": before}},
        abi=STORE_NUMBER_ABI,
    )
    adversary_status, _ = _adversary_write(ctx, before + 1)
    drifted = ctx.reader.get_storage_uint256(ctx.target, 0)
    stale = verify_state_snapshot_fresh(
        {"config": {"number": before}},
        {"config": {"number": drifted}},
        phase="prewrite",
    )

    recovery_mandate = _mandate(
        ctx,
        intent_suffix="recovery-fresh",
        before=drifted,
        goal=goal,
    )
    recovery_proposal = _proposal(ctx, goal)
    recovered, evidence, _, post = _verified_execution(
        ctx,
        recovery_mandate,
        recovery_proposal,
        before=drifted,
    )
    primary_tx = str(evidence.get("tx_hash", ""))
    adversary_tx = _tx_hash(adversary_status)
    return LiveBenchResult(
        "semantic_recovery_after_drift",
        "semantic_recovery",
        "detect_stale_state_then_replan_from_fresh_state_and_verify_goal",
        admission.approved and not stale.passed and recovered and post == goal,
        primary_write_calls=1 if primary_tx else 0,
        adversary_write_calls=1,
        transaction_hashes=tuple(tx for tx in (adversary_tx, primary_tx) if tx),
        evidence={
            "original_simulation_approved": admission.approved,
            "stale_detected": not stale.passed,
            "drifted_state": drifted,
            "goal": goal,
            "recovery_verified": recovered,
            "post": post,
        },
    )


def _case_fresh_intent_same_action(ctx: LiveContext) -> LiveBenchResult:
    before = ctx.reader.get_storage_uint256(ctx.target, 0)
    goal = before + 1
    mandate = _mandate(ctx, intent_suffix="fresh-same-action", before=before, goal=goal)
    proposal = _proposal(ctx, goal)
    replay_check = ctx.replay.check(mandate, proposal)
    admission = ctx.engine.admit_contract_call(
        mandate,
        proposal,
        pre_state={"config": {"number": before}},
        abi=STORE_NUMBER_ABI,
    )
    return LiveBenchResult(
        "fresh_intent_same_action",
        "control",
        "new_intent_id_is_not_false_positive_replay",
        replay_check.passed and admission.approved,
        evidence={
            "replay_guard_passed": replay_check.passed,
            "simulation_approved": admission.approved,
            "pre_state": before,
            "proposed_goal": goal,
        },
    )


CASE_FUNCTIONS: tuple[Callable[[LiveContext], LiveBenchResult], ...] = (
    _case_safe_live_control,
    _case_wrong_chain,
    _case_wrong_target,
    _case_wrong_function,
    _case_wrong_arguments,
    _case_malformed_target,
    _case_stale_snapshot_before_simulation,
    _case_simulation_execution_race,
    _case_duplicate_semantic_intent,
    _case_keeperhub_idempotency_replay,
    _case_post_state_drift,
    _case_receipt_hash_tampering,
    _case_proof_bundle_tampering,
    _case_semantic_recovery_after_drift,
    _case_fresh_intent_same_action,
)


def _result_to_dict(result: LiveBenchResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "category": result.category,
        "expectation": result.expectation,
        "correct": result.correct,
        "primary_write_calls": result.primary_write_calls,
        "adversary_write_calls": result.adversary_write_calls,
        "transaction_hashes": list(result.transaction_hashes),
        "evidence": result.evidence,
    }


def _run_case(ctx: LiveContext, function: Callable[[LiveContext], LiveBenchResult]) -> LiveBenchResult:
    try:
        return function(ctx)
    except Exception as exc:  # benchmark should report a failed row instead of losing the run
        return LiveBenchResult(
            name=function.__name__.removeprefix("_case_"),
            category="harness_error",
            expectation="scenario_completes_without_harness_error",
            correct=False,
            evidence={"error": f"{type(exc).__name__}: {exc}"},
        )


def _select_reader() -> BaseSepoliaReader:
    reader = BaseSepoliaReader(
        rpc_url=READ_RPC_CANDIDATES[0],
        fallback_rpc_urls=READ_RPC_CANDIDATES[1:],
        timeout=5.0,
        prefer_curl=True,
    )
    if reader.chain_id() != "84532":
        raise RuntimeError("Independent read layer did not return Base Sepolia chain 84532.")
    return reader


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the 15-case ProofPilot live adversarial benchmark.")
    parser.add_argument("--target", default=os.getenv("PROOFPILOT_DEMO_TARGET", DEFAULT_TARGET))
    parser.add_argument("--wrong-target", default=DEFAULT_WRONG_TARGET)
    parser.add_argument(
        "--case",
        choices=("all", *LIVE_SCENARIO_NAMES),
        action="append",
        default=None,
        help="Run selected scenarios; repeat --case to batch them. Default is all.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required: permits bounded Base Sepolia TESTNET writes used by live race/replay cases.",
    )
    args = parser.parse_args()

    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "message": "Pass --execute to run bounded Base Sepolia live writes.",
                    "scenarios": list(LIVE_SCENARIO_NAMES),
                },
                indent=2,
            )
        )
        return 0

    api_key = os.getenv("KH_API_KEY", "").strip()
    if not api_key.startswith("kh_"):
        print("KH_API_KEY must be provided via environment and start with kh_.", file=sys.stderr)
        return 2

    reader = _select_reader()
    if reader.chain_id() != "84532":
        print("Independent reader is not connected to Base Sepolia chain 84532.", file=sys.stderr)
        return 3

    client = McpHttpClient("https://app.keeperhub.com/mcp", bearer_token=api_key)
    client.initialize()
    live_tools = {tool.get("name") for tool in client.list_tools() if isinstance(tool, dict)}
    required = {"execute_contract_call", "get_direct_execution_status"}
    missing = sorted(required - live_tools)
    if missing:
        print(f"KeeperHub live MCP is missing required tools: {missing}", file=sys.stderr)
        return 4

    keeperhub = KeeperHubGate0(client)
    ctx = LiveContext(
        reader=reader,
        keeperhub=keeperhub,
        engine=IntentAssuranceEngine(keeperhub),
        replay=IntentReplayGuard(),
        target=args.target,
        wrong_target=args.wrong_target,
        run_id=uuid.uuid4().hex[:12],
    )

    if tuple(function.__name__.removeprefix("_case_") for function in CASE_FUNCTIONS) != LIVE_SCENARIO_NAMES:
        print("Internal scenario order does not match LIVE_SCENARIO_NAMES.", file=sys.stderr)
        return 5

    requested_cases = args.case or ["all"]
    selected_functions = CASE_FUNCTIONS
    if "all" not in requested_cases:
        selected_names = set(requested_cases)
        selected_functions = tuple(
            function
            for function in CASE_FUNCTIONS
            if function.__name__.removeprefix("_case_") in selected_names
        )

    starting_state = reader.get_storage_uint256(args.target, 0)
    results: list[LiveBenchResult] = []
    for function in selected_functions:
        result = _run_case(ctx, function)
        results.append(result)
        print(
            f"[{len(results):02d}/{len(selected_functions):02d}] {result.name}: "
            f"{'PASS' if result.correct else 'FAIL'}",
            file=sys.stderr,
            flush=True,
        )

    summary = summarize_live_results(results)
    payload = {
        "schema": "proofpilot.keeperbench.live.v1",
        "run_id": ctx.run_id,
        "network": {"name": "Base Sepolia", "chain_id": "84532"},
        "target": args.target,
        "starting_state": starting_state,
        "ending_state": reader.get_storage_uint256(args.target, 0),
        "results": [_result_to_dict(result) for result in results],
        "summary": summary.to_dict(),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if summary.correct == summary.total else 8


if __name__ == "__main__":
    raise SystemExit(main())

