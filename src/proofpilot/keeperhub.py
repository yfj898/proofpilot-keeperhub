from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from .config import BASE_SEPOLIA_CHAIN_ID
from .mcp import McpError, McpHttpClient
from .verifier import verify_terminal_execution


REQUIRED_GATE0_TOOLS = {
    "execute_transfer",
    "get_direct_execution_status",
}


@dataclass(frozen=True)
class ToolInventory:
    names: frozenset[str]
    execute_transfer_schema: dict[str, Any]


class KeeperHubGate0:
    def __init__(self, client: McpHttpClient):
        self.client = client

    def discover(self) -> ToolInventory:
        tools = self.client.list_tools()
        by_name = {tool.get("name"): tool for tool in tools if isinstance(tool, dict)}
        names = frozenset(name for name in by_name if isinstance(name, str))
        missing = REQUIRED_GATE0_TOOLS - names
        if missing:
            raise McpError(f"KeeperHub live MCP is missing required Gate 0 tools: {sorted(missing)}")
        transfer = by_name["execute_transfer"]
        schema = transfer.get("inputSchema") or {}
        if not _schema_mentions_simulate(schema):
            raise McpError("Live execute_transfer schema does not advertise a simulate field.", body=schema)
        return ToolInventory(names=names, execute_transfer_schema=schema)

    def simulate_native_transfer(self, *, recipient: str, amount: str) -> dict[str, Any]:
        result = self.client.call_tool(
            "execute_transfer",
            {
                "chain_id": BASE_SEPOLIA_CHAIN_ID,
                "to_address": recipient,
                "amount": amount,
                "simulate": True,
            },
        )
        normalized = _as_object(result, "simulate result")
        if normalized.get("success") is not True:
            raise McpError("Simulation did not return success=true.", body=normalized)
        if normalized.get("wouldRevert") is not False:
            raise McpError(
                "Simulation did not explicitly return wouldRevert=false.",
                body=normalized,
            )
        if str(normalized.get("status", "")).lower() != "simulated":
            raise McpError("Simulation did not explicitly return status=simulated.", body=normalized)
        return normalized

    def execute_native_transfer(self, *, recipient: str, amount: str) -> tuple[str, dict[str, Any]]:
        idempotency_key = f"proofpilot-{uuid.uuid4()}"
        result = self.client.call_tool(
            "execute_transfer",
            {
                "chain_id": BASE_SEPOLIA_CHAIN_ID,
                "to_address": recipient,
                "amount": amount,
                "idempotency_key": idempotency_key,
            },
        )
        normalized = _as_object(result, "broadcast result")
        return idempotency_key, normalized

    def simulate_contract_call(
        self,
        *,
        contract_address: str,
        function_name: str,
        function_args: str = "[]",
        abi: str = "",
        value: str = "0",
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "contract_address": contract_address,
            "chain_id": BASE_SEPOLIA_CHAIN_ID,
            "function_name": function_name,
            "function_args": function_args,
            "value": value,
            "simulate": True,
        }
        if abi:
            arguments["abi"] = abi
        result = self.client.call_tool("execute_contract_call", arguments)
        normalized = _as_object(result, "contract simulation result")
        if normalized.get("success") is not True:
            raise McpError("Contract simulation did not return success=true.", body=normalized)
        if normalized.get("wouldRevert") is not False:
            raise McpError(
                "Contract simulation did not explicitly return wouldRevert=false.",
                body=normalized,
            )
        if str(normalized.get("status", "")).lower() != "simulated":
            raise McpError(
                "Contract simulation did not explicitly return status=simulated.",
                body=normalized,
            )
        return normalized

    def execute_contract_call(
        self,
        *,
        contract_address: str,
        function_name: str,
        function_args: str = "[]",
        abi: str = "",
        value: str = "0",
        idempotency_key: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        idempotency_key = idempotency_key or f"proofpilot-intent-{uuid.uuid4()}"
        arguments: dict[str, Any] = {
            "contract_address": contract_address,
            "chain_id": BASE_SEPOLIA_CHAIN_ID,
            "function_name": function_name,
            "function_args": function_args,
            "value": value,
            "idempotency_key": idempotency_key,
        }
        if abi:
            arguments["abi"] = abi
        result = self.client.call_tool("execute_contract_call", arguments)
        return idempotency_key, _as_object(result, "contract broadcast result")

    def poll_status(
        self,
        execution_id: str,
        *,
        max_attempts: int = 12,
        delay_seconds: float = 1.0,
        max_delay_seconds: float = 5.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> dict[str, Any]:
        """Poll a KeeperHub direct execution with bounded backoff.

        MCP tool results may expose a poll hint, but unlike the REST surface they do not
        guarantee access to HTTP response headers. We therefore honor structured hints when
        present and otherwise use bounded exponential backoff. HTTP 429 responses from the
        MCP transport honor Retry-After when available and never trigger a new write.
        """

        last: dict[str, Any] = {}
        for attempt in range(max_attempts):
            try:
                result = self.client.call_tool(
                    "get_direct_execution_status",
                    {"execution_id": execution_id},
                )
            except McpError as exc:
                if exc.status != 429 or attempt + 1 >= max_attempts:
                    raise
                retry_after = exc.headers.get("retry-after")
                try:
                    next_delay = float(retry_after) if retry_after is not None else -1.0
                except (TypeError, ValueError):
                    next_delay = -1.0
                if next_delay < 0:
                    next_delay = min(max_delay_seconds, delay_seconds * (2**attempt))
                sleep_fn(max(0.0, min(max_delay_seconds, next_delay)))
                continue
            last = _as_object(result, "execution status")
            status = str(last.get("status", "")).lower()
            if status in {"completed", "failed"}:
                return last
            if attempt + 1 < max_attempts:
                hinted = last.get("pollIntervalHint") or last.get("poll_interval_hint")
                try:
                    next_delay = (
                        float(hinted)
                        if hinted is not None
                        else min(max_delay_seconds, delay_seconds * (2**attempt))
                    )
                except (TypeError, ValueError):
                    next_delay = min(max_delay_seconds, delay_seconds * (2**attempt))
                sleep_fn(max(0.0, min(max_delay_seconds, next_delay)))
        raise McpError(
            f"Execution {execution_id} did not reach a terminal state in {max_attempts} polls.",
            body=last,
        )


def verify_terminal_success(status: dict[str, Any]) -> tuple[bool, list[str]]:
    result = verify_terminal_execution(status)
    return result.passed, list(result.reasons)


def _schema_mentions_simulate(schema: Any) -> bool:
    if isinstance(schema, dict):
        if "simulate" in schema.get("properties", {}):
            return True
        return any(_schema_mentions_simulate(value) for value in schema.values())
    if isinstance(schema, list):
        return any(_schema_mentions_simulate(value) for value in schema)
    return False


def _as_object(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, dict):
        # Some MCP servers wrap structured data under a single result field.
        inner = value.get("result")
        if len(value) == 1 and isinstance(inner, dict):
            return inner
        return value
    raise McpError(f"KeeperHub {label} was not a JSON object.", body=value)

