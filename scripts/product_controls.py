from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from proofpilot.intent import ProposedAction, infer_contract_effects


EXECUTION_MODES = ("observe", "confirm", "autonomous")


@dataclass(frozen=True)
class BroadcastDecision:
    mode: str
    allowed: bool
    requires_human_confirmation: bool
    reason: str


def resolve_execution_mode(*, requested_mode: str | None, legacy_execute: bool) -> str:
    """Resolve the user-facing execution mode without weakening legacy safety semantics."""

    if requested_mode is not None and requested_mode not in EXECUTION_MODES:
        raise ValueError(f"unsupported execution mode: {requested_mode}")
    if legacy_execute:
        if requested_mode not in {None, "autonomous"}:
            raise ValueError("--execute is a compatibility alias for --mode autonomous")
        return "autonomous"
    return requested_mode or "observe"


def decide_broadcast(
    *,
    mode: str,
    explicit_confirm: bool,
    interactive: bool,
    input_func: Callable[[str], str] = input,
) -> BroadcastDecision:
    """Turn an approved simulation into a human-control decision.

    This function is intentionally downstream of deterministic intent checks and simulation.
    It never authorizes a proposal that failed those gates; it only determines whether an
    already-approved proposal may cross the final broadcast boundary.
    """

    if mode not in EXECUTION_MODES:
        raise ValueError(f"unsupported execution mode: {mode}")
    if mode == "observe":
        return BroadcastDecision(
            mode=mode,
            allowed=False,
            requires_human_confirmation=False,
            reason="Observe mode is simulation-only by construction.",
        )
    if mode == "autonomous":
        return BroadcastDecision(
            mode=mode,
            allowed=True,
            requires_human_confirmation=False,
            reason="Autonomous mode permits broadcast after all deterministic gates pass.",
        )
    if explicit_confirm:
        return BroadcastDecision(
            mode=mode,
            allowed=True,
            requires_human_confirmation=True,
            reason="Confirm mode received explicit non-interactive confirmation.",
        )
    if not interactive:
        return BroadcastDecision(
            mode=mode,
            allowed=False,
            requires_human_confirmation=True,
            reason="Confirm mode requires human approval; no interactive terminal was available.",
        )
    answer = input_func("Approve this exact simulated transaction? [y/N] ").strip().lower()
    allowed = answer in {"y", "yes"}
    return BroadcastDecision(
        mode=mode,
        allowed=allowed,
        requires_human_confirmation=True,
        reason=(
            "Human confirmed the exact simulated transaction."
            if allowed
            else "Human did not confirm the transaction."
        ),
    )


def build_candidate_action_preview(
    *,
    user_intent: str,
    proposal: ProposedAction,
    current_emode: int,
    execution_mode: str,
    network_name: str,
) -> dict[str, object]:
    """Build an explicitly unverified candidate-action diff before authorization."""

    target_emode: int | None = None
    if proposal.function_signature == "setUserEMode(uint8)" and len(proposal.arguments) == 1:
        value = proposal.arguments[0]
        if isinstance(value, int):
            target_emode = value

    changes: list[dict[str, object]] = []
    if target_emode is not None:
        changes.append(
            {
                "field": "Aave E-Mode category",
                "before": current_emode,
                "after": target_emode,
            }
        )
    else:
        changes.append(
            {
                "field": "Contract action",
                "before": "current onchain state",
                "after": f"{proposal.function_signature}{list(proposal.arguments)!r}",
            }
        )

    native_value = proposal.native_value if isinstance(proposal.native_value, Decimal) else Decimal("0")
    effects = sorted(infer_contract_effects(proposal.function_signature))
    return {
        "authorization_status": "UNVERIFIED_CANDIDATE",
        "user_intent": user_intent,
        "protocol": "Aave V3",
        "network": network_name,
        "execution_mode": execution_mode,
        "action": proposal.function_signature,
        "target_contract": proposal.target,
        "semantic_effects": effects,
        "changes": changes,
        "native_eth": format(native_value, "f"),
        "token_transfer": (
            "present"
            if "erc20.balance_transfer" in effects
            else ("unknown" if "unknown.contract_effect" in effects else "none")
        ),
        "collateral_settings": (
            "will change"
            if "aave.collateral_configuration" in effects
            else (
                "unknown / requires authorization review"
                if "unknown.contract_effect" in effects
                else "unchanged by this candidate action"
            )
        ),
    }


def render_candidate_action_preview(preview: dict[str, object]) -> str:
    lines = [
        "Candidate Action Preview — UNVERIFIED",
        f"  You asked: {preview['user_intent']}",
        f"  Protocol: {preview['protocol']}",
        f"  Network: {preview['network']}",
        f"  Execution mode: {str(preview['execution_mode']).upper()}",
        f"  Action: {preview['action']}",
    ]
    for change in preview.get("changes", []):
        if isinstance(change, dict):
            lines.append(
                f"  Change: {change.get('field')}: {change.get('before')} -> {change.get('after')}"
            )
    lines.extend(
        [
            f"  Native ETH sent: {preview['native_eth']}",
            f"  Token transfer: {preview['token_transfer']}",
            f"  Collateral settings: {preview['collateral_settings']}",
        ]
    )
    return "\n".join(lines)


# Backward-compatible aliases for older scripts/artifacts. New UI/docs call this a
# candidate preview because it is rendered before ProofPilot authorization.
build_intent_preview = build_candidate_action_preview
render_intent_preview = render_candidate_action_preview

