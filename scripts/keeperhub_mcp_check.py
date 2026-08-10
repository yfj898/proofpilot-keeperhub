from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.config import KEEPERHUB_MCP_URL  # noqa: E402
from proofpilot.mcp import McpError, McpHttpClient  # noqa: E402


REQUIRED_AGENT_NATIVE_TOOLS = (
    "execute_contract_call",
    "get_direct_execution_status",
    "list_integrations",
    "get_wallet_integration",
    "tools_documentation",
    "list_action_schemas",
    "search_protocol_actions",
    "execute_protocol_action",
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


def _contains_evm_address(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_evm_address(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_evm_address(item) for item in value)
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) != 42 or not text.startswith("0x"):
        return False
    try:
        int(text[2:], 16)
    except ValueError:
        return False
    return True


def build_report(
    *,
    client: McpHttpClient,
    endpoint: str,
) -> dict[str, Any]:
    initialized = client.initialize()
    tools = client.list_tools()
    names = sorted(
        tool.get("name")
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    )
    integrations = client.call_tool("list_integrations", {})
    required = {name: name in names for name in REQUIRED_AGENT_NATIVE_TOOLS}
    return {
        "schema": "proofpilot.keeperhub-mcp-check.v1",
        "endpoint": endpoint,
        "official_hosted_endpoint": endpoint == KEEPERHUB_MCP_URL,
        "initialize_http_status": initialized.status,
        "negotiated_mcp_protocol": client.protocol_version,
        "tool_count": len(names),
        "required_tools": required,
        "all_required_tools_present": all(required.values()),
        "wallet_integration_address_present": _contains_evm_address(integrations),
        "write_performed": False,
        "notes": [
            "This check performs MCP initialize, tools/list, and list_integrations only.",
            "It does not simulate, sign, submit, or broadcast a transaction.",
            "No bearer token or integration credential is serialized into this report.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only preflight for ProofPilot's direct connection to KeeperHub's official "
            "hosted agent-native MCP server."
        )
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--mcp-url", default=KEEPERHUB_MCP_URL)
    parser.add_argument("--artifact", default="artifacts/runtime/keeperhub-mcp-check.json")
    args = parser.parse_args(argv)

    file_env = _load_env_file(Path(args.env_file))
    api_key = os.getenv("KH_API_KEY", "").strip() or file_env.get("KH_API_KEY", "").strip()
    if not api_key.startswith("kh_") or len(api_key) < 20:
        print(
            "A valid organization-scoped KH_API_KEY must be supplied via the environment; "
            "placeholder values are rejected.",
            file=sys.stderr,
        )
        return 2

    client = McpHttpClient(args.mcp_url, bearer_token=api_key)
    try:
        report = build_report(client=client, endpoint=args.mcp_url)
    except McpError as exc:
        print(f"KeeperHub MCP preflight failed: {exc}", file=sys.stderr)
        return 3

    artifact = Path(args.artifact)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print("KeeperHub Official MCP Runtime Check")
    print(f"  Endpoint: {report['endpoint']}")
    print(f"  Initialize HTTP: {report['initialize_http_status']}")
    print(f"  MCP protocol: {report['negotiated_mcp_protocol']}")
    print(f"  Tools discovered: {report['tool_count']}")
    print(f"  Required tools present: {report['all_required_tools_present']}")
    print(f"  Wallet integration present: {report['wallet_integration_address_present']}")
    print("  Write performed: False")
    print(f"  Artifact: {artifact}")
    return 0 if report["all_required_tools_present"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
