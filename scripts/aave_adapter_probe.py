from __future__ import annotations

import json
import os
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.aave_adapter import AAVE_DEPOSIT_ETH_ABI, AaveEthSupplyAdapter  # noqa: E402
from proofpilot.intent import assure_intent  # noqa: E402
from proofpilot.keeperhub import KeeperHubGate0  # noqa: E402
from proofpilot.mcp import McpError, McpHttpClient  # noqa: E402


def _address(value: object) -> str | None:
    if isinstance(value, dict):
        for item in value.values():
            found = _address(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _address(item)
            if found:
                return found
    if isinstance(value, str) and re.fullmatch(r"0x[a-fA-F0-9]{40}", value):
        return value
    return None


def main() -> int:
    api_key = os.getenv("KH_API_KEY", "").strip()
    if not api_key.startswith("kh_"):
        print("KH_API_KEY is required in the environment.", file=sys.stderr)
        return 2
    client = McpHttpClient("https://app.keeperhub.com/mcp", bearer_token=api_key)
    client.initialize()
    account = _address(client.call_tool("list_integrations", {}))
    if not account:
        return 3
    adapter = AaveEthSupplyAdapter(account, Decimal("0.000001"))
    mandate = adapter.mandate(intent_id="proofpilot-aave-probe")
    proposal = adapter.proposal(mandate)
    intent = assure_intent(mandate, proposal)
    result = {"intent_pass": intent.passed, "broadcast": False, "simulation_pass": False}
    try:
        simulation = KeeperHubGate0(client).simulate_contract_call(
            contract_address=proposal.target,
            function_name="depositETH",
            function_args=json.dumps(list(proposal.arguments)),
            abi=AAVE_DEPOSIT_ETH_ABI,
            value=format(proposal.native_value, "f"),
        )
        result.update({"simulation_pass": True, "simulation": simulation})
    except McpError as exc:
        body = json.dumps(exc.body, ensure_ascii=False) if exc.body is not None else str(exc)
        selector = "0xf58f733a" if "0xf58f733a" in body else None
        result.update(
            {
                "simulation_pass": False,
                "would_revert": "wouldRevert\\\":true" in body or '"wouldRevert":true' in body,
                "error_selector": selector,
                "decoded_error": "SupplyCapExceeded()" if selector else None,
            }
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

