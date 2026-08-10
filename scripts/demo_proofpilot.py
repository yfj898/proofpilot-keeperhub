from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.aave_adapter import (  # noqa: E402
    AAVE_BASE_SEPOLIA_POOL,
    AAVE_BASE_SEPOLIA_USDC,
    AAVE_EXTERNAL_REDTEAM_ABI,
    AAVE_SET_USER_EMODE_ABI,
)
from proofpilot.execution_binding import (  # noqa: E402
    canonical_contract_call_payload,
    execution_payload_sha256,
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
from proofpilot.intent_ir import DelegationEnvelope  # noqa: E402
from proofpilot.execution_identity import (  # noqa: E402
    select_single_web3_integration,
    verify_supported_eoa_identity,
)
from proofpilot.keeperhub import KeeperHubGate0  # noqa: E402
from proofpilot.mandate_compiler import BindingProfile, MandateCompiler  # noqa: E402
from proofpilot.mcp import McpError, McpHttpClient  # noqa: E402
from proofpilot.operation_journal import (  # noqa: E402
    OperationJournal,
    ReconciliationRequired,
    operation_semantic_key,
)
from proofpilot.proof_bundle import (  # noqa: E402
    VERIFICATION_LEVEL_L2_EFFECT,
    build_execution_trace_v2,
    verify_execution_trace_v2,
)
from proofpilot.reader import BaseSepoliaReader  # noqa: E402
from proofpilot.verifier import (  # noqa: E402
    verify_aave_emode_execution_binding,
    verify_independent_receipt,
    verify_terminal_execution,
)
from agent_proposal import (  # noqa: E402
    AgentProposalError,
    NvidiaProposalAgent,
    build_agent_payload,
    candidate_to_proposed_action,
    compact_keeperhub_tools,
)
from product_controls import (  # noqa: E402
    EXECUTION_MODES,
    build_intent_preview,
    decide_broadcast,
    render_intent_preview,
    resolve_execution_mode,
)


DEFAULT_MCP_URL = "https://app.keeperhub.com/mcp"
BASE_SEPOLIA_CHAIN_ID = "84532"
DEFAULT_AGENT_MODEL = "deepseek-ai/deepseek-v4-flash-0731"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Canonical ProofPilot competition demo: NL intent -> typed Intent IR -> "
            "semantic assurance -> KeeperHub simulation/execution -> independent verification."
        )
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--mcp-url", default=DEFAULT_MCP_URL)
    parser.add_argument(
        "--category",
        type=int,
        default=None,
        help="Exact Aave E-Mode category. Default: choose 1 when current!=1, otherwise 0.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Compatibility alias for --mode autonomous.",
    )
    parser.add_argument(
        "--mode",
        choices=EXECUTION_MODES,
        default=None,
        help=(
            "User-control mode: observe=never broadcast; confirm=human approval after preview + "
            "simulation; autonomous=broadcast automatically after all gates pass. Default: observe."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Non-interactive human approval for --mode confirm after preview/simulation gates pass.",
    )
    parser.add_argument(
        "--attack",
        action="store_true",
        help=(
            "Demonstrate an executable semantic mismatch. This mode is hard-locked to "
            "simulation-only and can never broadcast."
        ),
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help=(
            "Use a real external LLM to generate the ProposedAction from the user intent and "
            "live-discovered KeeperHub tools. The model never receives KeeperHub credentials."
        ),
    )
    parser.add_argument("--agent-model", default=DEFAULT_AGENT_MODEL)
    parser.add_argument("--agent-timeout", type=float, default=60.0)
    parser.add_argument("--artifact", default="")
    parser.add_argument(
        "--journal",
        default=".proofpilot/operations.sqlite3",
        help="Crash-safe local operation journal used before any KeeperHub broadcast.",
    )
    args = parser.parse_args(argv)
    try:
        args.execution_mode = resolve_execution_mode(
            requested_mode=args.mode,
            legacy_execute=args.execute,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.attack and args.execution_mode != "observe":
        parser.error("--attack is observe-only by construction and can never broadcast")
    if args.attack and args.agent:
        parser.error("--attack is the deterministic adversarial demo; use --agent without --attack for the live AI proposal path")
    if args.confirm and args.execution_mode != "confirm":
        parser.error("--confirm is only valid with --mode confirm")
    if args.category is not None and not 0 <= args.category <= 255:
        parser.error("--category must fit uint8 (0..255)")
    if args.agent_timeout <= 0:
        parser.error("--agent-timeout must be positive")
    return args


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


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
    elif isinstance(value, str):
        text = value.strip()
        if len(text) == 42 and text.startswith("0x"):
            try:
                int(text[2:], 16)
            except ValueError:
                return None
            return text
    return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def _check_rows(result: Any) -> list[dict[str, Any]]:
    checks = getattr(result, "checks", ())
    return [
        {"name": check.name, "passed": bool(check.passed), "reason": check.reason}
        for check in checks
    ]


def _proposal_dict(proposal: ProposedAction) -> dict[str, Any]:
    return {
        "action": proposal.action.value,
        "chain_id": proposal.chain_id,
        "target": proposal.target,
        "function_signature": proposal.function_signature,
        "arguments": list(proposal.arguments),
        "native_value": format(proposal.native_value, "f"),
    }


def _choose_target_category(current: int, requested: int | None) -> int:
    if requested is not None:
        return requested
    return 1 if current != 1 else 0


def _choose_attack_category(current: int, intended: int) -> int:
    # Prefer an executable semantic no-op: keep the caller in its current category.
    if current != intended:
        return current
    # If the user explicitly requested the current state, force a different, known demo category.
    return 0 if intended != 0 else 1


def _semantic_deviations(
    intended: ProposedAction,
    observed: ProposedAction,
) -> list[str]:
    deviations: list[str] = []
    if observed.chain_id != intended.chain_id:
        deviations.append("wrong_chain")
    if observed.target.lower() != intended.target.lower():
        deviations.append("wrong_target")
    if observed.function_signature != intended.function_signature:
        deviations.append("wrong_function")
    if observed.arguments != intended.arguments:
        if (
            intended.function_signature == "setUserEMode(uint8)"
            and len(observed.arguments) == 1
            and len(intended.arguments) == 1
        ):
            deviations.append("wrong_emode_category")
        else:
            deviations.append("wrong_arguments")
    if observed.native_value != intended.native_value:
        deviations.append("unexpected_native_value")
    return deviations


def _artifact_path(args: argparse.Namespace) -> Path:
    if args.artifact:
        return Path(args.artifact)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mode = "attack" if args.attack else ("agent" if args.agent else "safe")
    return ROOT / f"artifacts/demo/proofpilot-{mode}-{stamp}.json"


def _to_execution_trace_v2(artifact: dict[str, Any]) -> dict[str, Any]:
    status = str(artifact.get("final_status") or "BLOCKED")
    status_map = {
        "SIMULATION_APPROVED": "SIMULATED",
        "BLOCKED_STALE_STATE": "BLOCKED",
        "DEMO_CONSTRUCTION_FAILED": "BLOCKED",
    }
    status = status_map.get(status, status)
    if status not in {
        "BLOCKED",
        "SIMULATED",
        "SIMULATION_FAILED",
        "EXECUTION_FAILED",
        "VERIFICATION_FAILED",
        "VERIFIED",
    }:
        status = "BLOCKED"

    keeperhub_execution = dict(artifact.get("keeperhub_execution") or {})
    submission = artifact.get("keeperhub_submission") or {}
    if submission:
        keeperhub_execution.setdefault("submission", submission)

    trace = build_execution_trace_v2(
        user_intent=str(artifact.get("user_intent") or ""),
        intent_ir=dict(artifact.get("intent_ir") or {}),
        intent_commitment=str(artifact.get("intent_commitment") or ""),
        proposal=dict(artifact.get("proposal") or {}),
        intent_assurance=dict(artifact.get("intent_assurance") or {}),
        pre_state=dict(artifact.get("pre_state") or {}),
        keeperhub_simulation=dict(artifact.get("keeperhub_simulation") or {}),
        final_status=status,
        broadcast_attempted=bool(artifact.get("broadcast_attempted")),
        network=dict(artifact.get("network") or {}),
        context={
            "verification_profile": "authorization_to_execution_v1",
            "mode": artifact.get("mode"),
            "execution_mode": artifact.get("execution_mode"),
            "account": artifact.get("account"),
            "keeperhub_mcp_connected": artifact.get("keeperhub", {}).get("mcp_connected"),
            "keeperhub_tool_count": artifact.get("keeperhub", {}).get("tool_count"),
            "agent": artifact.get("agent", {}),
            "intent_preview": artifact.get("intent_preview", {}),
            "execution_control": artifact.get("execution_control", {}),
            "execution_identity": artifact.get("execution_identity", {}),
            "operation_journal": artifact.get("operation_journal", {}),
        },
        precondition_checks=list(artifact.get("precondition_checks") or []),
        freshness_check=dict(artifact.get("freshness_check") or {}),
        semantic_deviations=list(artifact.get("independent_semantic_deviations") or []),
        execution_payload=dict(artifact.get("execution_payload") or {}),
        keeperhub_execution=keeperhub_execution,
        independent_receipt=dict(artifact.get("independent_receipt") or {}),
        execution_binding=dict(artifact.get("execution_binding") or {}),
        verification_level=str(artifact.get("verification_level") or ""),
        post_state=dict(artifact.get("post_state") or {}),
        postcondition_check=dict(artifact.get("postcondition_check") or {}),
        provenance={
            "compiler_version": (artifact.get("intent_ir") or {}).get("compiler_version"),
            "intent_commitment": artifact.get("intent_commitment"),
            "write_path": artifact.get("keeperhub", {}).get("write_path"),
        },
        final_reason=str(artifact.get("error") or ""),
        created_at=str(artifact.get("created_at") or datetime.now(timezone.utc).isoformat()),
    )
    if not verify_execution_trace_v2(trace):
        raise RuntimeError("Generated execution trace failed its own integrity verification.")
    return trace


def _write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    trace = _to_execution_trace_v2(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(trace), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _headline(title: str) -> None:
    print(f"\n[{title}]")


def _build_compiler() -> MandateCompiler:
    return MandateCompiler(
        {
            "aave_emode": BindingProfile(
                "aave_emode",
                "aave",
                AAVE_BASE_SEPOLIA_POOL,
                "setUserEMode(uint8)",
                AAVE_SET_USER_EMODE_ABI,
            )
        }
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    artifact_path = _artifact_path(args)
    file_env = _load_env_file(Path(args.env_file))
    kh_key = os.getenv("KH_API_KEY", "").strip() or file_env.get("KH_API_KEY", "").strip()
    if not kh_key.startswith("kh_"):
        print("KH_API_KEY is required via environment or the selected env file.", file=sys.stderr)
        return 2

    print("=" * 64)
    print("ProofPilot — Intent Firewall for Autonomous Onchain Agents")
    print("Network: Base Sepolia (84532)")
    mode_label = "ATTACK / OBSERVE" if args.attack else (
        f"LLM AGENT / {args.execution_mode.upper()}" if args.agent else
        f"DETERMINISTIC / {args.execution_mode.upper()}"
    )
    print("Mode:", mode_label)
    print("=" * 64)

    reader = BaseSepoliaReader(
        rpc_url="https://base-sepolia-rpc.publicnode.com",
        timeout=5,
        prefer_curl=True,
        fallback_rpc_urls=("https://84532.rpc.thirdweb.com", "https://sepolia.base.org"),
    )
    if reader.chain_id() != BASE_SEPOLIA_CHAIN_ID:
        print("Independent reader is not connected to Base Sepolia.", file=sys.stderr)
        return 3

    client = McpHttpClient(args.mcp_url, bearer_token=kh_key)
    client.initialize()
    tools = client.list_tools()
    tool_names = {
        str(tool.get("name"))
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    }
    required = {
        "list_integrations",
        "get_wallet_integration",
        "execute_contract_call",
        "get_direct_execution_status",
    }
    missing = required - tool_names
    if missing:
        print(f"KeeperHub MCP missing required tools: {sorted(missing)}", file=sys.stderr)
        return 4

    integrations = client.call_tool("list_integrations", {})
    integration = select_single_web3_integration(integrations)
    wallet_details = (
        client.call_tool("get_wallet_integration", {"integrationId": integration.get("id")})
        if integration and integration.get("id")
        else None
    )
    identity_check = verify_supported_eoa_identity(
        integration,
        wallet_details if isinstance(wallet_details, dict) else None,
    )
    account = (
        str((wallet_details or {}).get("walletAddress") or integration.get("address") or "")
        if integration
        else ""
    )
    if not account:
        print("No EVM integration address found in KeeperHub.", file=sys.stderr)
        return 5
    if not identity_check.passed and args.execution_mode != "observe":
        print(
            "UNSUPPORTED_EXECUTION_IDENTITY: only the verified direct-web3 EOA profile may "
            "enter Confirm/Autonomous execution.",
            file=sys.stderr,
        )
        return 5

    keeperhub = KeeperHubGate0(client)
    pre_emode = reader.aave_user_emode(AAVE_BASE_SEPOLIA_POOL, account)
    target_category = _choose_target_category(pre_emode, args.category)

    _headline("1/7 KeeperHub + independent state")
    print(f"KeeperHub MCP: CONNECTED ({len(tool_names)} tools)")
    print(f"Aave Pool: {AAVE_BASE_SEPOLIA_POOL}")
    print(f"Current E-Mode (independent Base RPC): {pre_emode}")

    user_intent = (
        f"Set my Aave E-Mode category exactly to {target_category}. "
        "Do not change collateral settings. Attach no native ETH."
    )
    delegation = DelegationEnvelope(
        delegation_id="proofpilot-competition-demo-aave",
        allowed_protocols=frozenset({"aave"}),
        allowed_targets=frozenset({AAVE_BASE_SEPOLIA_POOL}),
        allowed_functions=frozenset({"setUserEMode(uint8)"}),
        max_native_value=Decimal("0"),
    )
    intent = _build_compiler().compile(
        user_intent,
        delegation=delegation,
        account=account,
        nonce=int(time.time()),
        intent_id=f"competition-demo-aave-emode-{int(time.time())}",
    )
    mandate = IntentMandate(
        intent_id=intent.intent_id,
        chain_id=intent.chain_id,
        action=IntentAction.CONTRACT_CALL,
        target=intent.action.target,
        function_signature=intent.action.function_signature,
        exact_arguments=intent.action.arguments,
        exact_native_value=intent.action.native_value,
        preconditions=(StateCondition("aave.user_emode", "eq", pre_emode),),
        postconditions=(StateCondition("aave.user_emode", "eq", target_category),),
        forbidden_effects=tuple(intent.metadata.get("forbidden_effects") or ()),
        description=user_intent,
    )
    intended_proposal = ProposedAction(
        action=IntentAction.CONTRACT_CALL,
        chain_id=intent.chain_id,
        target=intent.action.target,
        function_signature=intent.action.function_signature,
        arguments=intent.action.arguments,
        native_value=intent.action.native_value,
    )

    _headline("2/7 User intent -> typed Intent IR")
    print("User intent:", user_intent)
    print("Intent commitment:", intent.commitment())
    print("Bound action:", intended_proposal.function_signature, list(intended_proposal.arguments))

    artifact: dict[str, Any] = {
        "schema": "proofpilot.competition-demo.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "testnet_only": True,
        "mode": "attack" if args.attack else ("agent" if args.agent else "safe"),
        "execution_mode": args.execution_mode,
        "network": {"name": "Base Sepolia", "chain_id": BASE_SEPOLIA_CHAIN_ID},
        "keeperhub": {
            "mcp_connected": True,
            "required_tools_present": True,
            "tool_count": len(tool_names),
            "write_path": "KeeperHub MCP execute_contract_call",
        },
        "account": account,
        "execution_identity": {
            "profile": "keeperhub_direct_web3_eoa_v1",
            "supported": identity_check.passed,
            "checks": _check_rows(identity_check),
            "safe_or_active_sender_supported": False,
        },
        "user_intent": user_intent,
        "intent_ir": _json_safe(intent.canonical_dict()),
        "intent_commitment": intent.commitment(),
        "pre_state": {"aave": {"user_emode": pre_emode}},
        "broadcast_attempted": False,
    }

    if args.attack:
        attack_category = _choose_attack_category(pre_emode, target_category)
        proposal = ProposedAction(
            action=IntentAction.CONTRACT_CALL,
            chain_id=BASE_SEPOLIA_CHAIN_ID,
            target=AAVE_BASE_SEPOLIA_POOL,
            function_signature="setUserEMode(uint8)",
            arguments=(attack_category,),
            native_value=Decimal("0"),
        )
        deviations = _semantic_deviations(intended_proposal, proposal)
        decision = assure_intent(mandate, proposal)
        artifact["proposal"] = _proposal_dict(proposal)
        artifact["independent_semantic_deviations"] = deviations
        artifact["intent_assurance"] = {
            "passed": decision.passed,
            "checks": _check_rows(decision),
        }

        preview = build_intent_preview(
            user_intent=user_intent,
            proposal=proposal,
            current_emode=pre_emode,
            execution_mode="observe",
            network_name="Base Sepolia",
        )
        artifact["intent_preview"] = preview

        _headline("3/7 Adversarial proposal")
        print("Proposal:", proposal.function_signature, list(proposal.arguments))
        print("Independent semantic deviation:", ", ".join(deviations) or "NONE")
        print(render_intent_preview(preview))

        _headline("4/7 ProofPilot Intent Assurance")
        for check in decision.checks:
            print(("  ✓ " if check.passed else "  ✗ ") + check.name)
        if decision.passed or not deviations:
            artifact["final_status"] = "DEMO_CONSTRUCTION_FAILED"
            artifact["error"] = "Attack proposal did not create an independently labeled semantic mismatch."
            _write_artifact(artifact_path, artifact)
            print("Artifact:", artifact_path)
            return 6

        _headline("5/7 KeeperHub simulation evidence")
        print("Broadcast is disabled in --attack mode.")
        try:
            simulation = keeperhub.simulate_contract_call(
                contract_address=proposal.target,
                function_name="setUserEMode",
                function_args=json.dumps(list(proposal.arguments), separators=(",", ":")),
                abi=AAVE_SET_USER_EMODE_ABI,
                value="0",
            )
            artifact["keeperhub_simulation"] = simulation
            print("KeeperHub simulation: EXECUTABLE (success=true, non-reverting)")
        except McpError as exc:
            artifact["keeperhub_simulation"] = {"passed": False, "error": str(exc)}
            print("KeeperHub simulation: NOT EXECUTABLE")

        _headline("6/7 Broadcast gate")
        print("ProofPilot: BLOCKED")
        print("Broadcast attempted: NO")
        artifact["final_status"] = "BLOCKED"
        artifact["broadcast_attempted"] = False

        _headline("7/7 Evidence")
        _write_artifact(artifact_path, artifact)
        print("Executable != Intended")
        print("Artifact:", artifact_path)
        return 0

    proposal = intended_proposal
    if args.agent:
        nvidia_key = os.getenv("GUARDIAN_LLM_API_KEY", "").strip() or file_env.get(
            "GUARDIAN_LLM_API_KEY", ""
        ).strip()
        nvidia_base = os.getenv("GUARDIAN_LLM_BASE_URL", "").strip() or file_env.get(
            "GUARDIAN_LLM_BASE_URL", "https://integrate.api.nvidia.com/v1"
        ).strip()
        if not nvidia_key:
            artifact["final_status"] = "BLOCKED"
            artifact["error"] = "LLM agent mode requires GUARDIAN_LLM_API_KEY."
            _write_artifact(artifact_path, artifact)
            print("LLM agent API key is missing; no proposal or broadcast occurred.", file=sys.stderr)
            print("Artifact:", artifact_path)
            return 7

        discovered_tools = compact_keeperhub_tools(tools)
        action_surface = json.loads(AAVE_EXTERNAL_REDTEAM_ABI)
        agent_payload = build_agent_payload(
            user_intent=user_intent,
            current_state={
                "chain_id": BASE_SEPOLIA_CHAIN_ID,
                "aave_pool": AAVE_BASE_SEPOLIA_POOL,
                "caller_emode_category": pre_emode,
                "known_test_asset": AAVE_BASE_SEPOLIA_USDC,
                "testnet_only": True,
            },
            discovered_tools=discovered_tools,
            contract_abi=action_surface,
        )
        _headline("3/7 Live LLM agent proposal")
        print("KeeperHub tools discovered live:", ", ".join(row["name"] for row in discovered_tools))
        try:
            candidate = NvidiaProposalAgent(
                api_key=nvidia_key,
                base_url=nvidia_base,
                model=args.agent_model,
                timeout=args.agent_timeout,
            ).propose(agent_payload)
            artifact["agent"] = {
                "source": "external_llm_proposal_agent",
                "requested_model": candidate.requested_model,
                "provider_model": candidate.provider_model,
                "decision": candidate.decision,
                "execution_tool": candidate.execution_tool,
                "reason": candidate.reason,
                "prompt_sha256": candidate.prompt_sha256,
                "prompt_tokens": candidate.prompt_tokens,
                "completion_tokens": candidate.completion_tokens,
                "keeperhub_tools_discovered_live": [row["name"] for row in discovered_tools],
                "keeperhub_credentials_visible_to_model": False,
                "model_has_direct_keeperhub_tool_access": False,
            }
            if candidate.decision == "abstain":
                artifact["final_status"] = "BLOCKED"
                artifact["error"] = "LLM agent abstained instead of proposing a transaction."
                _write_artifact(artifact_path, artifact)
                print("Agent abstained; fail-closed before KeeperHub simulation.")
                print("Artifact:", artifact_path)
                return 7
            proposal = candidate_to_proposed_action(
                candidate,
                contract_abi=action_surface,
                discovered_tool_names=tool_names,
            )
        except AgentProposalError as exc:
            artifact["final_status"] = "BLOCKED"
            artifact["error"] = f"LLM agent proposal rejected before KeeperHub: {exc}"
            _write_artifact(artifact_path, artifact)
            print("Agent proposal invalid; fail-closed before KeeperHub simulation.")
            print("Artifact:", artifact_path)
            return 7
        print("LLM proposal:", proposal.function_signature, list(proposal.arguments))
        print("Selected KeeperHub tool:", candidate.execution_tool)
    else:
        _headline("3/7 Deterministic reference proposal")
        print("Proposal:", proposal.function_signature, list(proposal.arguments))

    artifact["proposal"] = _proposal_dict(proposal)
    preview = build_intent_preview(
        user_intent=user_intent,
        proposal=proposal,
        current_emode=pre_emode,
        execution_mode=args.execution_mode,
        network_name="Base Sepolia",
    )
    artifact["intent_preview"] = preview
    print(render_intent_preview(preview))

    _headline("4/7 ProofPilot + KeeperHub preflight")
    admission = IntentAssuranceEngine(keeperhub).admit_contract_call(
        mandate,
        proposal,
        pre_state={"aave": {"user_emode": pre_emode}},
        abi=AAVE_SET_USER_EMODE_ABI,
        expected_sender=account,
    )
    artifact["intent_assurance"] = {
        "passed": admission.intent_check.passed,
        "checks": _check_rows(admission.intent_check),
    }
    artifact["precondition_checks"] = (
        _check_rows(admission.precondition_check) if admission.precondition_check else []
    )
    artifact["keeperhub_simulation"] = admission.simulation or {}
    artifact["simulation_binding_check"] = (
        {
            "passed": admission.simulation_binding_check.passed,
            "checks": _check_rows(admission.simulation_binding_check),
        }
        if admission.simulation_binding_check
        else {"passed": False, "checks": []}
    )
    artifact["execution_payload"] = {
        "sha256": admission.execution_payload_sha256,
        "commitment_match": bool(admission.execution_payload_sha256),
        "canonical": {
            key: value
            for key, value in (admission.execution_payload or {}).items()
            if key != "abi"
        },
    }
    artifact["simulation_check"] = (
        {
            "passed": admission.simulation_check.passed,
            "checks": _check_rows(admission.simulation_check),
        }
        if admission.simulation_check
        else {"passed": False, "checks": []}
    )
    for check in admission.intent_check.checks:
        print(("  ✓ " if check.passed else "  ✗ ") + check.name)
    print("KeeperHub simulation:", "PASS" if admission.approved else "FAIL")
    if not admission.approved:
        preconditions_ok = bool(
            admission.precondition_check is not None and admission.precondition_check.passed
        )
        artifact["final_status"] = (
            "SIMULATION_FAILED"
            if admission.intent_check.passed and preconditions_ok
            else "BLOCKED"
        )
        artifact["error"] = admission.error
        _write_artifact(artifact_path, artifact)
        print("Artifact:", artifact_path)
        return 7

    broadcast = decide_broadcast(
        mode=args.execution_mode,
        explicit_confirm=args.confirm,
        interactive=sys.stdin.isatty(),
    )
    artifact["execution_control"] = {
        "mode": broadcast.mode,
        "broadcast_allowed": broadcast.allowed,
        "requires_human_confirmation": broadcast.requires_human_confirmation,
        "control_authority": "local_cli_operator",
        "authenticated_user_signature": False,
        "reason": broadcast.reason,
    }
    if not broadcast.allowed:
        _headline("5/7 Execution")
        print(broadcast.reason)
        print("No transaction was broadcast.")
        artifact["final_status"] = "SIMULATION_APPROVED"
        _headline("6/7 Outcome verification")
        print("Skipped because no transaction was broadcast.")
        _headline("7/7 Evidence")
        _write_artifact(artifact_path, artifact)
        print("Artifact:", artifact_path)
        return 0

    _headline("5/7 Guarded KeeperHub execution")
    print("Execution control:", broadcast.reason)
    fresh_emode = reader.aave_user_emode(AAVE_BASE_SEPOLIA_POOL, account)
    freshness = verify_state_snapshot_fresh(
        {"aave": {"user_emode": pre_emode}},
        {"aave": {"user_emode": fresh_emode}},
        phase="prebroadcast_fresh",
    )
    artifact["freshness_check"] = {
        "passed": freshness.passed,
        "checks": _check_rows(freshness),
        "observed_emode": fresh_emode,
    }
    if not freshness.passed:
        artifact["final_status"] = "BLOCKED_STALE_STATE"
        _write_artifact(artifact_path, artifact)
        print("State drift detected. Broadcast blocked.")
        print("Artifact:", artifact_path)
        return 8

    broadcast_payload = canonical_contract_call_payload(proposal, abi=AAVE_SET_USER_EMODE_ABI)
    broadcast_payload_sha = execution_payload_sha256(broadcast_payload)
    payload_commitment_match = (
        bool(admission.execution_payload_sha256)
        and broadcast_payload_sha == admission.execution_payload_sha256
    )
    artifact["execution_payload"]["broadcast_sha256"] = broadcast_payload_sha
    artifact["execution_payload"]["commitment_match"] = payload_commitment_match
    if not payload_commitment_match:
        artifact["final_status"] = "BLOCKED"
        artifact["error"] = "Canonical execution payload changed after simulation."
        _write_artifact(artifact_path, artifact)
        print("Execution payload changed after simulation; broadcast blocked.")
        print("Artifact:", artifact_path)
        return 8

    journal = OperationJournal(ROOT / args.journal)
    semantic_key = operation_semantic_key(
        account=account,
        user_intent=user_intent,
    )
    try:
        operation = journal.prepare(
            semantic_key=semantic_key,
            intent_commitment=intent.commitment(),
            payload_sha256=broadcast_payload_sha,
        )
    except ReconciliationRequired as exc:
        artifact["final_status"] = "BLOCKED"
        artifact["error"] = f"RECONCILIATION_REQUIRED: {exc}"
        _write_artifact(artifact_path, artifact)
        print("Unresolved write requires reconciliation; no new broadcast was attempted.")
        print("Artifact:", artifact_path)
        return 9

    artifact["operation_journal"] = {
        "operation_id": operation.operation_id,
        "state_before_execution": operation.state,
        "payload_sha256": operation.payload_sha256,
        "idempotency_key_persisted_before_broadcast": True,
    }

    execution_id = operation.execution_id
    submit: dict[str, Any] = {}
    if execution_id:
        idempotency_key = operation.idempotency_key
        artifact["broadcast_attempted"] = True
        print("Recovered unresolved operation; reusing the persisted execution id/idempotency key.")
    else:
        idempotency_key, submit = keeperhub.execute_contract_call(
            contract_address=str(broadcast_payload["contract_address"]),
            function_name=str(broadcast_payload["function_name"]),
            function_args=str(broadcast_payload["function_args"]),
            abi=str(broadcast_payload["abi"]),
            value=str(broadcast_payload["value"]),
            idempotency_key=operation.idempotency_key,
        )
        artifact["broadcast_attempted"] = True
        execution_id = submit.get("executionId") or submit.get("execution_id") or submit.get("id")
        if execution_id:
            operation = journal.mark_submitted(operation.operation_id, str(execution_id))
    artifact["keeperhub_submission"] = {
        "idempotency_key": idempotency_key,
        "execution_id": execution_id,
        "status": submit.get("status") if submit else operation.state,
    }
    if not execution_id:
        artifact["final_status"] = "EXECUTION_FAILED"
        artifact["error"] = "KeeperHub broadcast response did not include an execution id."
        _write_artifact(artifact_path, artifact)
        print("KeeperHub execution id missing.")
        print("Artifact:", artifact_path)
        return 9

    status = keeperhub.poll_status(
        str(execution_id), max_attempts=18, delay_seconds=1.0, max_delay_seconds=5.0
    )
    terminal = verify_terminal_execution(status)
    tx_hash = status.get("transactionHash") or status.get("transaction_hash")
    if str(status.get("status", "")).lower() == "failed":
        journal.mark_failed(operation.operation_id)
    elif tx_hash:
        operation = journal.mark_confirmed(operation.operation_id, str(tx_hash))
    artifact["keeperhub_execution"] = {
        "execution_id": execution_id,
        "status": status.get("status"),
        "transaction_hash": tx_hash,
        "transaction_link": status.get("transactionLink") or status.get("transaction_link"),
        "terminal_check": {"passed": terminal.passed, "checks": _check_rows(terminal)},
    }
    print("KeeperHub terminal status:", status.get("status"))
    print("Transaction:", tx_hash or "<missing>")

    _headline("6/7 Independent outcome verification")
    receipt = reader.get_transaction_receipt(str(tx_hash)) if tx_hash else None
    transaction = reader.get_transaction(str(tx_hash)) if tx_hash else None
    receipt_check = verify_independent_receipt(str(tx_hash), receipt) if tx_hash else None
    execution_binding = verify_aave_emode_execution_binding(
        transaction=transaction,
        receipt=receipt,
        pool=AAVE_BASE_SEPOLIA_POOL,
        account=account,
        category_id=int(proposal.arguments[0]),
        simulated_sender=str((admission.simulation or {}).get("from", "")),
    )
    post_emode = reader.aave_user_emode(AAVE_BASE_SEPOLIA_POOL, account)
    postcondition = verify_state_conditions(
        mandate.postconditions,
        {"aave": {"user_emode": post_emode}},
        phase="post",
    )
    artifact["independent_receipt"] = {
        "passed": bool(receipt_check and receipt_check.passed),
        "checks": _check_rows(receipt_check) if receipt_check else [],
        "transaction_hash": receipt.get("transactionHash") if receipt else None,
        "status": receipt.get("status") if receipt else None,
        "block_number": receipt.get("blockNumber") if receipt else None,
        "block_hash": receipt.get("blockHash") if receipt else None,
    }
    artifact["execution_binding"] = {
        "profile": "keeperhub_envelope_plus_aave_effect_v1",
        "passed": execution_binding.passed,
        "checks": _check_rows(execution_binding),
        "outer_transaction": {
            "from": transaction.get("from") if transaction else None,
            "to": transaction.get("to") if transaction else None,
            "value": transaction.get("value") if transaction else None,
        },
        "full_call_trace_verified": False,
        "note": (
            "Independent public RPC does not expose debug_traceTransaction; binding uses "
            "KeeperHub envelope account/target evidence plus Aave UserEModeSet event identity/effect."
        ),
    }
    artifact["post_state"] = {"aave": {"user_emode": post_emode}}
    artifact["postcondition_check"] = {
        "passed": postcondition.passed,
        "checks": _check_rows(postcondition),
    }
    verified = (
        terminal.passed
        and bool(receipt_check and receipt_check.passed)
        and execution_binding.passed
        and payload_commitment_match
        and postcondition.passed
    )
    artifact["verification_level"] = (
        VERIFICATION_LEVEL_L2_EFFECT if verified else "L2_EXECUTION_EFFECT_UNVERIFIED"
    )
    artifact["final_status"] = "VERIFIED" if verified else "VERIFICATION_FAILED"
    if verified:
        operation = journal.mark_verified(operation.operation_id)
    artifact["operation_journal"]["state_after_verification"] = operation.state
    print(f"Aave E-Mode: {pre_emode} -> {post_emode}")
    print("Independent receipt:", "PASS" if receipt_check and receipt_check.passed else "FAIL")
    print("Authorization-to-execution binding:", "PASS" if execution_binding.passed else "FAIL")
    print("Postcondition:", "PASS" if postcondition.passed else "FAIL")

    _headline("7/7 Evidence")
    _write_artifact(artifact_path, artifact)
    print("Final:", artifact["final_status"])
    print("Artifact:", artifact_path)
    return 0 if verified else 10


if __name__ == "__main__":
    raise SystemExit(main())
