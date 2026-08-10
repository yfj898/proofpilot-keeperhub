from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.proof_bundle import EXECUTION_TRACE_SCHEMA, verify_execution_trace_v2  # noqa: E402


def _mark(passed: bool) -> str:
    return "✓" if passed else "✗"


def _line(label: str, value: Any, *, indent: int = 2) -> str:
    return f"{' ' * indent}{label}: {value}"


def render_trace(trace: dict[str, Any]) -> str:
    lines: list[str] = []
    integrity = verify_execution_trace_v2(trace)
    lines.append("ProofPilot Execution Trace")
    lines.append("=" * 64)
    lines.append(_line("Schema", trace.get("schema")))
    lines.append(_line("Trace ID", trace.get("trace_id")))
    network = trace.get("network") or {}
    lines.append(_line("Network", f"{network.get('name')} ({network.get('chain_id')})"))
    lines.append(_line("Integrity", f"{_mark(integrity)} SHA-256 verified"))

    intent = trace.get("intent") or {}
    ir = intent.get("ir") or {}
    ir_action = ir.get("action") or {}
    lines.append("")
    lines.append("Intent")
    lines.append(_line("User", intent.get("source_text")))
    lines.append(_line("Intent hash", intent.get("source_text_sha256")))
    lines.append(_line("Commitment", intent.get("commitment")))
    if ir_action:
        lines.append(
            _line(
                "Bound action",
                f"{ir_action.get('function_signature')} {ir_action.get('arguments')}",
            )
        )

    proposal = (trace.get("proposal") or {}).get("action") or {}
    context = trace.get("context") or {}
    preview = context.get("intent_preview") or {}
    control = context.get("execution_control") or {}
    if preview:
        lines.append("")
        lines.append("Intent Preview")
        lines.append(_line("Protocol", preview.get("protocol")))
        lines.append(_line("Execution mode", str(preview.get("execution_mode") or "").upper()))
        for change in preview.get("changes") or []:
            if isinstance(change, dict):
                lines.append(
                    _line(
                        "Change",
                        f"{change.get('field')}: {change.get('before')} -> {change.get('after')}",
                    )
                )
        lines.append(_line("Native ETH", preview.get("native_eth")))
        lines.append(_line("Token transfer", preview.get("token_transfer")))
        lines.append(_line("Collateral settings", preview.get("collateral_settings")))

    lines.append("")
    lines.append("Proposal")
    lines.append(_line("Target", proposal.get("target")))
    lines.append(_line("Function", proposal.get("function_signature")))
    lines.append(_line("Arguments", proposal.get("arguments")))
    lines.append(_line("Native value", proposal.get("native_value")))
    lines.append(_line("Proposal hash", (trace.get("proposal") or {}).get("sha256")))

    authorization = trace.get("authorization") or {}
    assurance = authorization.get("intent_assurance") or {}
    lines.append("")
    lines.append("Intent Assurance")
    for check in assurance.get("checks") or []:
        lines.append(_line(f"{_mark(bool(check.get('passed')))} {check.get('name')}", check.get("reason")))
    deviations = authorization.get("independent_semantic_deviations") or []
    if deviations:
        lines.append(_line("Independent semantic deviations", ", ".join(str(x) for x in deviations)))

    keeperhub = trace.get("keeperhub") or {}
    simulation = keeperhub.get("simulation") or {}
    lines.append("")
    lines.append("KeeperHub")
    if simulation:
        sim_success = simulation.get("success") is True and simulation.get("wouldRevert") is False
        lines.append(_line("Simulation", f"{_mark(sim_success)} success={simulation.get('success')} wouldRevert={simulation.get('wouldRevert')}"))
        if simulation.get("gasEstimate") is not None:
            lines.append(_line("Gas estimate", simulation.get("gasEstimate")))
    else:
        lines.append(_line("Simulation", "not available"))

    execution = keeperhub.get("execution") or {}
    if execution:
        submission = execution.get("submission") or {}
        lines.append(_line("Execution ID", execution.get("execution_id") or submission.get("execution_id")))
        lines.append(_line("Status", execution.get("status") or submission.get("status")))
        lines.append(_line("Transaction", execution.get("transaction_hash")))
        terminal = execution.get("terminal_check") or {}
        if terminal:
            lines.append(_line("Terminal check", f"{_mark(bool(terminal.get('passed')))} {terminal.get('passed')}"))
    else:
        lines.append(_line("Execution", "none"))
    if control:
        lines.append(_line("Execution mode", str(control.get("mode") or "").upper()))
        lines.append(_line("Broadcast allowed by user control", control.get("broadcast_allowed")))
        lines.append(_line("Control reason", control.get("reason")))

    verification = trace.get("verification") or {}
    receipt = verification.get("independent_receipt") or {}
    postcondition = verification.get("postcondition_check") or {}
    lines.append("")
    lines.append("Outcome Verification")
    if receipt:
        lines.append(_line("Independent receipt", f"{_mark(bool(receipt.get('passed')))} {receipt.get('passed')}"))
    else:
        lines.append(_line("Independent receipt", "not applicable"))
    if verification.get("post_state"):
        lines.append(_line("Post-state", json.dumps(verification.get("post_state"), sort_keys=True)))
    if postcondition:
        lines.append(_line("Postcondition", f"{_mark(bool(postcondition.get('passed')))} {postcondition.get('passed')}"))
    else:
        lines.append(_line("Postcondition", "not applicable"))

    lines.append("")
    lines.append("Final")
    status = str(trace.get("final_status") or "UNKNOWN")
    lines.append(_line("Status", status))
    if trace.get("final_reason"):
        lines.append(_line("Reason", trace.get("final_reason")))
    lines.append(_line("Broadcast attempted", trace.get("broadcast_attempted")))
    lines.append(_line("Trace integrity", "PASS" if integrity else "FAIL"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a ProofPilot execution trace offline.")
    parser.add_argument("trace", help="Path to proofpilot.execution-trace.v2 JSON")
    args = parser.parse_args(argv)
    path = Path(args.trace)
    try:
        trace = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Trace not found: {path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"Trace is not valid JSON: {exc}", file=sys.stderr)
        return 3
    if not isinstance(trace, dict) or trace.get("schema") != EXECUTION_TRACE_SCHEMA:
        print(f"Unsupported trace schema; expected {EXECUTION_TRACE_SCHEMA}.", file=sys.stderr)
        return 4
    print(render_trace(trace))
    return 0 if verify_execution_trace_v2(trace) else 5


if __name__ == "__main__":
    raise SystemExit(main())
