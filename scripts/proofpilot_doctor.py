from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from proofpilot.aave_adapter import (  # noqa: E402
    AAVE_BASE_SEPOLIA_POOL,
    AAVE_BASE_SEPOLIA_USDC,
    AAVE_EXTERNAL_REDTEAM_ABI,
)
from proofpilot.config import KEEPERHUB_MCP_URL  # noqa: E402
from proofpilot.execution_identity import (  # noqa: E402
    select_single_web3_integration,
    verify_supported_eoa_identity,
)
from proofpilot.mcp import McpError, McpHttpClient  # noqa: E402
from proofpilot.reader import BaseSepoliaReader, ReadLayerError  # noqa: E402
from agent_proposal import (  # noqa: E402
    AgentProposalError,
    NvidiaProposalAgent,
    build_agent_payload,
    candidate_to_proposed_action,
    compact_keeperhub_tools,
)


BASE_SEPOLIA_CHAIN_ID = "84532"
DEFAULT_AGENT_MODEL = "deepseek-ai/deepseek-v4-flash-0731"
REQUIRED_TOOLS = {
    "execute_contract_call",
    "get_direct_execution_status",
    "list_integrations",
    "get_wallet_integration",
    "list_action_schemas",
    "search_protocol_actions",
}
DOCTOR_READ_ONLY_TOOL_CALLS = frozenset(
    {
        "list_integrations",
        "get_wallet_integration",
        "list_action_schemas",
        "search_protocol_actions",
    }
)


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


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    if status not in {"PASS", "WARN", "FAIL", "SKIP"}:
        raise ValueError("invalid doctor status")
    return {"name": name, "status": status, "detail": detail}


def _final_status(checks: list[dict[str, str]]) -> str:
    if any(row["status"] == "FAIL" for row in checks):
        return "NOT_READY"
    if any(row["status"] == "WARN" for row in checks):
        return "READY_WITH_WARNINGS"
    return "READY"


def _agent_probe_matches_expected(proposal: Any) -> bool:
    return bool(
        getattr(proposal, "chain_id", None) == BASE_SEPOLIA_CHAIN_ID
        and str(getattr(proposal, "target", "")).lower() == AAVE_BASE_SEPOLIA_POOL.lower()
        and getattr(proposal, "function_signature", None) == "setUserEMode(uint8)"
        and getattr(proposal, "arguments", None) == (1,)
        and getattr(proposal, "native_value", None) == Decimal("0")
    )


def _base_sepolia_is_stable(action_schemas: Any) -> bool:
    if not isinstance(action_schemas, dict):
        return False
    for chain in action_schemas.get("chains", []) or []:
        if not isinstance(chain, dict):
            continue
        chain_id = str(chain.get("chainId") or chain.get("chain_id") or chain.get("id") or "")
        if chain_id == BASE_SEPOLIA_CHAIN_ID:
            return str(chain.get("status") or "").lower() == "stable"
    return False


def _aave_protocol_actions(protocol_actions: Any) -> list[str]:
    if not isinstance(protocol_actions, dict):
        return []
    rows: list[str] = []
    for action in protocol_actions.get("actions", []) or []:
        if not isinstance(action, dict):
            continue
        action_type = str(action.get("actionType") or "")
        if action_type.startswith("aave-v3/"):
            rows.append(action_type)
    return sorted(set(rows))


def build_doctor_report(
    *,
    env_file: Path,
    mcp_url: str,
    probe_agent: bool,
    agent_model: str,
    agent_timeout: float,
) -> dict[str, Any]:
    file_env = _load_env_file(env_file)
    kh_key = os.getenv("KH_API_KEY", "").strip() or file_env.get("KH_API_KEY", "").strip()
    nvidia_key = os.getenv("GUARDIAN_LLM_API_KEY", "").strip() or file_env.get(
        "GUARDIAN_LLM_API_KEY", ""
    ).strip()
    nvidia_base = os.getenv("GUARDIAN_LLM_BASE_URL", "").strip() or file_env.get(
        "GUARDIAN_LLM_BASE_URL", "https://integrate.api.nvidia.com/v1"
    ).strip()

    checks: list[dict[str, str]] = []
    checks.append(
        _check(
            "keeperhub_api_key",
            "PASS" if kh_key.startswith("kh_") and len(kh_key) >= 20 else "FAIL",
            "Organization-scoped KeeperHub credential is configured."
            if kh_key.startswith("kh_") and len(kh_key) >= 20
            else "A non-placeholder KH_API_KEY is required.",
        )
    )
    checks.append(
        _check(
            "agent_api_key",
            "PASS" if bool(nvidia_key) else "FAIL",
            "Proposal-agent credential is configured."
            if nvidia_key
            else "GUARDIAN_LLM_API_KEY is required for the AI Agent runtime.",
        )
    )
    checks.append(
        _check(
            "official_keeperhub_endpoint",
            "PASS" if mcp_url == KEEPERHUB_MCP_URL else "WARN",
            mcp_url,
        )
    )

    account = ""
    tools: list[dict[str, Any]] = []
    keeperhub_tool_calls: list[str] = []
    if checks[0]["status"] == "PASS":
        try:
            client = McpHttpClient(mcp_url, bearer_token=kh_key, timeout=20.0)
            init = client.initialize()
            tools = client.list_tools()
            tool_names = {
                str(row.get("name"))
                for row in tools
                if isinstance(row, dict) and isinstance(row.get("name"), str)
            }
            missing = sorted(REQUIRED_TOOLS - tool_names)
            checks.append(
                _check(
                    "keeperhub_mcp",
                    "PASS" if init.status == 200 and not missing else "FAIL",
                    f"HTTP {init.status}; MCP {client.protocol_version}; tools={len(tool_names)}; missing={missing}",
                )
            )
            keeperhub_tool_calls.append("list_integrations")
            integrations = client.call_tool("list_integrations", {})
            integration = select_single_web3_integration(integrations)
            wallet_details: dict[str, Any] | None = None
            if integration and integration.get("id"):
                keeperhub_tool_calls.append("get_wallet_integration")
                details = client.call_tool(
                    "get_wallet_integration",
                    {"integrationId": integration.get("id")},
                )
                if isinstance(details, dict):
                    wallet_details = details
            identity = verify_supported_eoa_identity(integration, wallet_details)
            account = (
                str((wallet_details or {}).get("walletAddress") or integration.get("address") or "")
                if integration
                else ""
            )
            checks.append(
                _check(
                    "wallet_integration",
                    "PASS" if account else "FAIL",
                    "EVM execution address is available."
                    if account
                    else "No EVM integration address was found.",
                )
            )
            checks.append(
                _check(
                    "execution_identity_profile",
                    "PASS" if identity.passed else "FAIL",
                    (
                        "Direct KeeperHub web3 EOA profile verified; Safe/active-Sender execution "
                        "remains intentionally unsupported."
                        if identity.passed
                        else "Execution identity is ambiguous, Safe-configured, or outside the "
                        "currently verified direct-web3 EOA profile."
                    ),
                )
            )
            keeperhub_tool_calls.append("list_action_schemas")
            action_schemas = client.call_tool(
                "list_action_schemas",
                {"category": "web3", "includeChains": True},
            )
            base_stable = _base_sepolia_is_stable(action_schemas)
            checks.append(
                _check(
                    "keeperhub_chain_schema",
                    "PASS" if base_stable else "FAIL",
                    "Base Sepolia (84532) is present and marked stable in live KeeperHub action schemas."
                    if base_stable
                    else "Base Sepolia (84532) was not present as a stable chain in live KeeperHub action schemas.",
                )
            )

            try:
                keeperhub_tool_calls.append("search_protocol_actions")
                protocol_actions = client.call_tool(
                    "search_protocol_actions",
                    {"protocol": "aave-v3"},
                )
                aave_actions = _aave_protocol_actions(protocol_actions)
                checks.append(
                    _check(
                        "keeperhub_aave_catalog",
                        "PASS" if aave_actions else "WARN",
                        (
                            f"Informational KeeperHub Aave V3 catalog: {len(aave_actions)} actions "
                            f"({', '.join(aave_actions)}). The Base Sepolia E-Mode demo does NOT "
                            "use this protocol plugin; it uses generic execute_contract_call."
                            if aave_actions
                            else (
                                "No Aave V3 catalog actions were returned. This does not block the "
                                "Base Sepolia E-Mode demo, which uses execute_contract_call."
                            )
                        ),
                    )
                )
            except McpError as exc:
                checks.append(
                    _check(
                        "keeperhub_aave_catalog",
                        "WARN",
                        (
                            "Aave protocol catalog discovery failed, but it is informational for "
                            f"the Base Sepolia contract-call demo: {exc}"
                        ),
                    )
                )
        except McpError as exc:
            checks.append(_check("keeperhub_mcp", "FAIL", str(exc)))
            checks.append(_check("wallet_integration", "FAIL", "Skipped because MCP preflight failed."))
            checks.append(_check("execution_identity_profile", "FAIL", "Skipped because MCP preflight failed."))
            checks.append(_check("keeperhub_chain_schema", "FAIL", "Skipped because MCP preflight failed."))
            checks.append(_check("keeperhub_aave_catalog", "WARN", "Skipped because MCP preflight failed."))
    else:
        checks.append(_check("keeperhub_mcp", "SKIP", "No valid KeeperHub credential."))
        checks.append(_check("wallet_integration", "SKIP", "No valid KeeperHub credential."))
        checks.append(_check("execution_identity_profile", "SKIP", "No valid KeeperHub credential."))
        checks.append(_check("keeperhub_chain_schema", "SKIP", "No valid KeeperHub credential."))
        checks.append(_check("keeperhub_aave_catalog", "SKIP", "No valid KeeperHub credential."))

    reader = BaseSepoliaReader(
        rpc_url="https://base-sepolia-rpc.publicnode.com",
        timeout=5,
        prefer_curl=True,
        fallback_rpc_urls=("https://84532.rpc.thirdweb.com", "https://sepolia.base.org"),
    )
    try:
        chain_id = reader.chain_id()
        checks.append(
            _check(
                "independent_base_rpc",
                "PASS" if chain_id == BASE_SEPOLIA_CHAIN_ID else "FAIL",
                f"chain_id={chain_id}",
            )
        )
    except ReadLayerError as exc:
        checks.append(_check("independent_base_rpc", "FAIL", str(exc)))

    native_balance: Decimal | None = None
    current_emode: int | None = None
    if account:
        try:
            native_balance = reader.get_native_balance(account)
            checks.append(
                _check(
                    "wallet_native_gas",
                    "PASS" if native_balance > 0 else "WARN",
                    (
                        f"wallet native balance={native_balance} ETH"
                        if native_balance > 0
                        else "Wallet native balance is zero; gas sponsorship may help direct-wallet writes, but active-sender funding must still be checked."
                    ),
                )
            )
        except (ReadLayerError, ValueError) as exc:
            checks.append(_check("wallet_native_gas", "WARN", str(exc)))
        try:
            code = reader.get_code(AAVE_BASE_SEPOLIA_POOL)
            current_emode = reader.aave_user_emode(AAVE_BASE_SEPOLIA_POOL, account)
            checks.append(
                _check(
                    "aave_readiness",
                    "PASS" if code != "0x" else "FAIL",
                    f"Aave Pool code present; current E-Mode={current_emode}",
                )
            )
        except (ReadLayerError, ValueError) as exc:
            checks.append(_check("aave_readiness", "FAIL", str(exc)))
    else:
        checks.append(_check("wallet_native_gas", "SKIP", "No wallet address available."))
        checks.append(_check("aave_readiness", "SKIP", "No wallet address available."))

    agent_probe: dict[str, Any] = {"performed": False}
    if probe_agent and nvidia_key and current_emode is not None and tools:
        try:
            discovered = compact_keeperhub_tools(tools)
            payload = build_agent_payload(
                user_intent="Set my Aave E-Mode category exactly to 1. Do not change collateral settings. Attach no native ETH.",
                current_state={
                    "chain_id": BASE_SEPOLIA_CHAIN_ID,
                    "aave_pool": AAVE_BASE_SEPOLIA_POOL,
                    "caller_emode_category": current_emode,
                    "known_test_asset": AAVE_BASE_SEPOLIA_USDC,
                    "testnet_only": True,
                },
                discovered_tools=discovered,
                contract_abi=json.loads(AAVE_EXTERNAL_REDTEAM_ABI),
            )
            candidate = NvidiaProposalAgent(
                api_key=nvidia_key,
                base_url=nvidia_base,
                model=agent_model,
                timeout=agent_timeout,
            ).propose(payload)
            proposal = candidate_to_proposed_action(
                candidate,
                contract_abi=json.loads(AAVE_EXTERNAL_REDTEAM_ABI),
                discovered_tool_names={row["name"] for row in discovered},
            )
            if not _agent_probe_matches_expected(proposal):
                raise AgentProposalError(
                    "Agent probe returned a valid ABI action that did not match the known readiness intent"
                )
            checks.append(
                _check(
                    "agent_live_probe",
                    "PASS",
                    f"model={candidate.provider_model}; proposed={proposal.function_signature}; no KeeperHub tool was invoked by the model",
                )
            )
            agent_probe = {
                "performed": True,
                "passed": True,
                "model": candidate.provider_model,
                "prompt_sha256": candidate.prompt_sha256,
                "proposal_function": proposal.function_signature,
            }
        except (AgentProposalError, ValueError) as exc:
            checks.append(
                _check(
                    "agent_live_probe",
                    "WARN",
                    f"Transient/model-level readiness probe did not produce the known safe action: {exc}. "
                    "The real Agent runtime still fails closed before KeeperHub simulation if this recurs.",
                )
            )
            agent_probe = {"performed": True, "passed": False, "error": str(exc)}
    elif probe_agent:
        checks.append(_check("agent_live_probe", "FAIL", "Agent probe prerequisites were not satisfied."))
    else:
        checks.append(_check("agent_live_probe", "SKIP", "Use --probe-agent for a live proposal-only model check."))

    doctor_read_only = set(keeperhub_tool_calls).issubset(DOCTOR_READ_ONLY_TOOL_CALLS)
    checks.append(
        _check(
            "doctor_read_only_surface",
            "PASS" if doctor_read_only else "FAIL",
            (
                "Only read-only KeeperHub discovery tools were invoked; no simulation or execution tool was called."
                if doctor_read_only
                else "Doctor invoked a KeeperHub tool outside its frozen read-only discovery allowlist."
            ),
        )
    )
    return {
        "schema": "proofpilot.doctor.v1",
        "testnet_only": True,
        "network": {"name": "Base Sepolia", "chain_id": BASE_SEPOLIA_CHAIN_ID},
        "write_performed": False if doctor_read_only else None,
        "read_only_contract": {
            "keeperhub_tools_invoked": keeperhub_tool_calls,
            "allowed_keeperhub_tools": sorted(DOCTOR_READ_ONLY_TOOL_CALLS),
            "simulation_invoked": False,
            "execution_invoked": False,
        },
        "account_present": bool(account),
        "wallet_native_balance_eth": str(native_balance) if native_balance is not None else None,
        "current_aave_emode": current_emode,
        "agent_probe": agent_probe,
        "checks": checks,
        "status": _final_status(checks),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only ProofPilot runtime readiness check. It performs KeeperHub discovery, "
            "independent RPC reads and an optional proposal-only LLM probe; it never simulates "
            "or executes a transaction."
        )
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--mcp-url", default=KEEPERHUB_MCP_URL)
    parser.add_argument("--probe-agent", action="store_true")
    parser.add_argument("--agent-model", default=DEFAULT_AGENT_MODEL)
    parser.add_argument("--agent-timeout", type=float, default=60.0)
    parser.add_argument("--artifact", default="artifacts/runtime/proofpilot-doctor.json")
    args = parser.parse_args(argv)

    report = build_doctor_report(
        env_file=Path(args.env_file),
        mcp_url=args.mcp_url,
        probe_agent=args.probe_agent,
        agent_model=args.agent_model,
        agent_timeout=args.agent_timeout,
    )
    artifact = Path(args.artifact)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print("ProofPilot Doctor — read-only readiness check (no simulation or execution)")
    for row in report["checks"]:
        print(f"  [{row['status']:<4}] {row['name']}: {row['detail']}")
    print("  Write performed: False")
    print(f"  Final: {report['status']}")
    print(f"  Artifact: {artifact}")
    return 0 if report["status"] in {"READY", "READY_WITH_WARNINGS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

