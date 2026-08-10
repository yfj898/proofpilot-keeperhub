from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class McpError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.body = body
        self.headers = headers or {}


@dataclass
class JsonRpcResponse:
    status: int
    headers: dict[str, str]
    payload: dict[str, Any]


class McpHttpClient:
    """Small stateless HTTP client sufficient for KeeperHub Gate 0.

    KeeperHub currently negotiates MCP protocol 2025-06-18 on its hosted endpoint.
    The class intentionally keeps the JSON-RPC surface tiny: initialize, tools/list,
    and tools/call.
    """

    def __init__(self, endpoint: str, bearer_token: str = "", timeout: float = 30.0):
        self.endpoint = endpoint
        self.bearer_token = bearer_token
        self.timeout = timeout
        self.protocol_version = "2025-06-18"
        self.session_id: str | None = None
        self._next_id = 1

    def initialize(self, *, authenticated: bool | None = None) -> JsonRpcResponse:
        if authenticated is None:
            authenticated = bool(self.bearer_token)
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "proofpilot-gate0", "version": "0.1.0"},
            },
            include_auth=authenticated,
        )
        negotiated = result.payload.get("result", {}).get("protocolVersion")
        if isinstance(negotiated, str) and negotiated:
            self.protocol_version = negotiated
        session_id = result.headers.get("mcp-session-id")
        if session_id:
            self.session_id = session_id
            self._notify("notifications/initialized", {}, include_auth=authenticated)
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        response = self._rpc("tools/list", {})
        tools = response.payload.get("result", {}).get("tools")
        if not isinstance(tools, list):
            raise McpError("KeeperHub tools/list did not return a tool list.", body=response.payload)
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        response = self._rpc("tools/call", {"name": name, "arguments": arguments})
        result = response.payload.get("result")
        if not isinstance(result, dict):
            raise McpError(f"Tool {name} returned an unexpected result.", body=response.payload)
        if result.get("isError") is True:
            raise McpError(f"KeeperHub tool {name} reported an error.", body=result)
        return decode_tool_result(result)

    def _rpc(
        self,
        method: str,
        params: dict[str, Any],
        *,
        include_auth: bool = True,
    ) -> JsonRpcResponse:
        request_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Protocol-Version": self.protocol_version,
            # The hosted endpoint currently sits behind a Cloudflare rule that can
            # reject Python urllib's default user-agent with Error 1010.  An explicit
            # conventional HTTP user-agent makes the exact same TLS client succeed.
            "User-Agent": "curl/8.5.0",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if include_auth and self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                parsed = _decode_http_payload(raw, response.headers.get("content-type", ""))
                if not isinstance(parsed, dict):
                    raise McpError("KeeperHub returned a non-object JSON-RPC payload.", body=parsed)
                if "error" in parsed:
                    raise McpError(f"JSON-RPC error for {method}", status=response.status, body=parsed)
                return JsonRpcResponse(
                    status=response.status,
                    headers={k.lower(): v for k, v in response.headers.items()},
                    payload=parsed,
                )
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
            raise McpError(
                f"HTTP {exc.code} from KeeperHub for {method}",
                status=exc.code,
                body=parsed,
                headers={k.lower(): v for k, v in exc.headers.items()},
            ) from exc
        except urllib.error.URLError as exc:
            raise McpError(f"Network error talking to KeeperHub: {exc.reason}") from exc

    def _notify(
        self,
        method: str,
        params: dict[str, Any],
        *,
        include_auth: bool = True,
    ) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Protocol-Version": self.protocol_version,
            "User-Agent": "curl/8.5.0",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if include_auth and self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                # MCP notifications intentionally have no JSON-RPC response body.
                response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise McpError(
                f"HTTP {exc.code} from KeeperHub for {method}",
                status=exc.code,
                body=raw,
            ) from exc
        except urllib.error.URLError as exc:
            raise McpError(f"Network error talking to KeeperHub: {exc.reason}") from exc


def _decode_http_payload(raw: str, content_type: str) -> Any:
    # KeeperHub currently answers JSON directly, but tolerate a simple SSE envelope
    # so Gate 0 does not break if the transport switches to text/event-stream.
    if "text/event-stream" in content_type:
        data_lines = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
        if not data_lines:
            raise McpError("Empty SSE response from KeeperHub.")
        return json.loads("\n".join(data_lines))
    return json.loads(raw)


def decode_tool_result(result: dict[str, Any]) -> Any:
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    content = result.get("content")
    if not isinstance(content, list):
        return result
    texts = [item.get("text") for item in content if isinstance(item, dict) and item.get("type") == "text"]
    texts = [text for text in texts if isinstance(text, str)]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            return texts[0]
    return texts or result

