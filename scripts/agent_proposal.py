from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


AGENT_SYSTEM_PROMPT = """You are the proposal agent inside ProofPilot, a TESTNET-only onchain agent.
You may propose one candidate onchain action, but you have no transaction authority and cannot call
tools yourself. ProofPilot will deterministically verify your proposal before KeeperHub is allowed
to simulate or execute it. Use only the KeeperHub tools and Aave action surface supplied by the
user payload. Try to fulfill the user's intent exactly. If the intent cannot be fulfilled from the
supplied information, abstain instead of guessing. Return JSON only and do not expose hidden
reasoning; use at most one short reason sentence."""


class AgentProposalError(ValueError):
    pass


@dataclass(frozen=True)
class AgentCandidate:
    decision: str
    execution_tool: str
    proposal: dict[str, Any] | None
    reason: str
    requested_model: str
    provider_model: str
    prompt_sha256: str
    raw_response: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def compact_keeperhub_tools(tools: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return a small, model-visible inventory derived from live MCP tools/list output."""

    interesting = {
        "execute_contract_call",
        "get_direct_execution_status",
        "search_protocol_actions",
        "execute_protocol_action",
        "list_action_schemas",
    }
    rows: list[dict[str, str]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if not isinstance(name, str) or name not in interesting:
            continue
        description = tool.get("description")
        rows.append(
            {
                "name": name,
                "description": str(description or "")[:500],
            }
        )
    return sorted(rows, key=lambda row: row["name"])


def build_agent_payload(
    *,
    user_intent: str,
    current_state: dict[str, Any],
    discovered_tools: list[dict[str, str]],
    contract_abi: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "user_intent": user_intent,
        "current_state": current_state,
        "keeperhub_tools_discovered_live": discovered_tools,
        "aave_action_surface_abi": contract_abi,
        "required_output": {
            "decision": "propose or abstain",
            "execution_tool": "one discovered KeeperHub tool name; use execute_contract_call for ABI calls",
            "proposal": {
                "chain_id": "string",
                "target": "0x-prefixed EVM address",
                "function_signature": "function signature present in the supplied ABI",
                "arguments": "JSON array matching that ABI function",
                "native_value": "non-negative decimal string in ETH",
            },
            "reason": "one short sentence",
        },
    }


def agent_prompt_sha256(
    payload: dict[str, Any],
    *,
    system_prompt: str = AGENT_SYSTEM_PROMPT,
) -> str:
    user_prompt = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((system_prompt + "\n" + user_prompt).encode("utf-8")).hexdigest()


class NvidiaProposalAgent:
    """OpenAI-compatible NVIDIA NIM proposal generator with no KeeperHub credentials/tools."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
        temperature: float = 0.2,
    ) -> None:
        if not api_key.strip():
            raise ValueError("NVIDIA API key is required")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    def propose(self, payload: dict[str, Any]) -> AgentCandidate:
        user_prompt = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        prompt_sha256 = agent_prompt_sha256(payload)
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "proofpilot-agent-runtime/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AgentProposalError(f"NVIDIA HTTP {exc.code}: {body[:500]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AgentProposalError(f"NVIDIA request failed: {exc}") from exc

        try:
            text = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AgentProposalError("NVIDIA response did not contain assistant content") from exc
        if not isinstance(text, str) or not text.strip():
            raise AgentProposalError("NVIDIA returned empty assistant content")

        parsed = _extract_json_object(text)
        decision = str(parsed.get("decision", "")).strip().lower()
        if decision not in {"propose", "abstain"}:
            raise AgentProposalError("Agent decision must be 'propose' or 'abstain'")
        execution_tool = str(parsed.get("execution_tool", "")).strip()
        proposal = parsed.get("proposal")
        if decision == "propose" and not isinstance(proposal, dict):
            raise AgentProposalError("Agent proposal must be a JSON object when decision=propose")
        if decision == "abstain":
            proposal = None

        usage = result.get("usage") if isinstance(result, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        return AgentCandidate(
            decision=decision,
            execution_tool=execution_tool,
            proposal=proposal,
            reason=str(parsed.get("reason", ""))[:240],
            requested_model=self.model,
            provider_model=str(result.get("model") or self.model),
            prompt_sha256=prompt_sha256,
            raw_response=text,
            prompt_tokens=_optional_int(usage.get("prompt_tokens")),
            completion_tokens=_optional_int(usage.get("completion_tokens")),
        )


def candidate_to_proposed_action(
    candidate: AgentCandidate,
    *,
    contract_abi: list[dict[str, Any]],
    discovered_tool_names: set[str],
):
    """Deterministically bind model JSON to the supplied ABI without broadening its authority."""

    from proofpilot.intent import IntentAction, ProposedAction

    if candidate.decision != "propose" or candidate.proposal is None:
        raise AgentProposalError("Agent abstained; no proposal is available")
    if candidate.execution_tool not in discovered_tool_names:
        raise AgentProposalError("Agent selected a KeeperHub tool that was not discovered live")
    if candidate.execution_tool != "execute_contract_call":
        raise AgentProposalError("This bounded Aave demo requires KeeperHub execute_contract_call")

    raw = candidate.proposal
    chain_id = str(raw.get("chain_id", "")).strip()
    target = str(raw.get("target", "")).strip()
    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", target):
        raise AgentProposalError("Agent proposal target is not a valid EVM address")
    target = target.lower()

    signature = re.sub(r"\s+", "", str(raw.get("function_signature", "")))
    functions = _abi_functions(contract_abi)
    by_name: dict[str, list[str]] = {}
    for known_signature in functions:
        by_name.setdefault(known_signature.split("(", 1)[0], []).append(known_signature)
    if signature not in functions and signature in by_name and len(by_name[signature]) == 1:
        signature = by_name[signature][0]
    function_abi = functions.get(signature)
    if function_abi is None:
        raise AgentProposalError("Agent selected a function outside the supplied Aave action surface")

    raw_arguments = raw.get("arguments")
    if isinstance(raw_arguments, str):
        # Some OpenAI-compatible providers occasionally serialize the requested
        # JSON array one level too deep (for example, "[1]").  Parsing that string
        # is a shape normalization only: the ABI, function, argument count/types,
        # target, and mandate checks still remain deterministic and unchanged.
        try:
            raw_arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise AgentProposalError("Agent proposal arguments string is not valid JSON") from exc
    if not isinstance(raw_arguments, list):
        raise AgentProposalError("Agent proposal arguments must be a JSON array")
    inputs = function_abi.get("inputs", [])
    if len(raw_arguments) != len(inputs):
        raise AgentProposalError("Agent proposal argument count does not match ABI")
    arguments = tuple(
        _canonical_abi_value(str(spec.get("type", "")), value)
        for value, spec in zip(raw_arguments, inputs)
    )

    try:
        native_value = Decimal(str(raw.get("native_value", "0")))
    except InvalidOperation as exc:
        raise AgentProposalError("Agent native_value must be numeric") from exc
    if not native_value.is_finite() or native_value < 0:
        raise AgentProposalError("Agent native_value must be finite and non-negative")

    return ProposedAction(
        action=IntentAction.CONTRACT_CALL,
        chain_id=chain_id,
        target=target,
        function_signature=signature,
        arguments=arguments,
        native_value=native_value,
        metadata={
            "source": "llm_agent",
            "execution_tool": candidate.execution_tool,
            "model": candidate.provider_model,
            "prompt_sha256": candidate.prompt_sha256,
        },
    )


def _abi_functions(abi: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    functions: dict[str, dict[str, Any]] = {}
    for item in abi:
        if not isinstance(item, dict) or item.get("type") != "function":
            continue
        name = item.get("name")
        inputs = item.get("inputs", [])
        if not isinstance(name, str) or not isinstance(inputs, list):
            continue
        types = [str(spec.get("type", "")) for spec in inputs if isinstance(spec, dict)]
        if len(types) != len(inputs) or any(not value for value in types):
            continue
        functions[f"{name}({','.join(types)})"] = item
    return functions


def _canonical_abi_value(type_name: str, value: Any) -> Any:
    if type_name == "address":
        text = str(value)
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", text):
            raise AgentProposalError("invalid address argument")
        return text.lower()
    uint_match = re.fullmatch(r"uint([0-9]*)", type_name)
    if uint_match:
        if isinstance(value, bool):
            raise AgentProposalError("bool cannot bind to uint")
        if isinstance(value, int):
            number = value
        elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            number = int(value)
        else:
            raise AgentProposalError("invalid uint argument")
        bits = int(uint_match.group(1) or "256")
        if bits < 8 or bits > 256 or bits % 8 != 0 or number < 0 or number >= 2**bits:
            raise AgentProposalError("uint argument out of range")
        return number
    if type_name == "bool":
        if not isinstance(value, bool):
            raise AgentProposalError("invalid bool argument")
        return value
    raise AgentProposalError(f"unsupported ABI type: {type_name}")


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AgentProposalError("Agent response was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise AgentProposalError("Agent response JSON must be an object")
    return parsed


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
