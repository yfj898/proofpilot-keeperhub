from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        lines.append(line)
    returncode = process.wait()
    return subprocess.CompletedProcess(command, returncode, "".join(lines), "")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def build_summary(
    *,
    doctor_path: Path,
    trace_path: Path,
    live: bool,
) -> dict[str, Any]:
    doctor = _load_json(doctor_path)
    trace = _load_json(trace_path)
    execution = (trace.get("keeperhub") or {}).get("execution") or {}
    tx_hash = execution.get("transaction_hash")
    expected_runtime_status = "VERIFIED" if live else "SIMULATED"
    return {
        "schema": "proofpilot.competition-demo-summary.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "testnet_only": True,
        "mode": "autonomous-live" if live else "observe",
        "doctor": {
            "status": doctor.get("status"),
            "write_performed": doctor.get("write_performed"),
            "artifact": str(doctor_path.relative_to(ROOT)),
        },
        "runtime": {
            "final_status": trace.get("final_status"),
            "broadcast_attempted": trace.get("broadcast_attempted"),
            "transaction_hash": tx_hash,
            "trace_id": trace.get("trace_id"),
            "artifact": str(trace_path.relative_to(ROOT)),
        },
        "success": (
            doctor.get("status") in {"READY", "READY_WITH_WARNINGS"}
            and doctor.get("write_performed") is False
            and trace.get("final_status") == expected_runtime_status
            and (bool(trace.get("broadcast_attempted")) if live else not bool(trace.get("broadcast_attempted")))
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-command ProofPilot competition demo: read-only Doctor first, then the AI Agent "
            "runtime. Default is Observe (no write); --live explicitly enables Autonomous testnet execution."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run the AI Agent in Autonomous mode on Base Sepolia after Doctor reports ready.",
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--agent-model", default="deepseek-ai/deepseek-v4-flash-0731")
    parser.add_argument("--agent-timeout", type=float, default=90.0)
    parser.add_argument("--artifact", default="artifacts/runtime/competition-demo-summary.json")
    args = parser.parse_args(argv)

    doctor_path = ROOT / "artifacts/runtime/competition-demo-doctor.json"
    trace_path = ROOT / (
        "artifacts/demo/competition-demo-autonomous.json"
        if args.live
        else "artifacts/demo/competition-demo-observe.json"
    )

    print("ProofPilot Competition Demo")
    print("=" * 64)
    print("[1/2] Runtime Doctor")
    doctor_cmd = [
        sys.executable,
        "scripts/proofpilot_doctor.py",
        "--probe-agent",
        "--env-file",
        args.env_file,
        "--agent-model",
        args.agent_model,
        "--agent-timeout",
        str(args.agent_timeout),
        "--artifact",
        str(doctor_path.relative_to(ROOT)),
    ]
    doctor_run = _run(doctor_cmd)
    if doctor_run.returncode != 0:
        print("Doctor did not report READY; Agent runtime will not start.", file=sys.stderr)
        return doctor_run.returncode

    print("\n[2/2] AI Agent Runtime")
    mode = "autonomous" if args.live else "observe"
    demo_cmd = [
        sys.executable,
        "scripts/demo_proofpilot.py",
        "--agent",
        "--mode",
        mode,
        "--env-file",
        args.env_file,
        "--agent-model",
        args.agent_model,
        "--agent-timeout",
        str(args.agent_timeout),
        "--artifact",
        str(trace_path.relative_to(ROOT)),
    ]
    demo_run = _run(demo_cmd)
    if demo_run.returncode != 0:
        return demo_run.returncode

    summary = build_summary(doctor_path=doctor_path, trace_path=trace_path, live=args.live)
    output = ROOT / args.artifact
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    print("\nCompetition Demo Summary")
    print(f"  Doctor: {summary['doctor']['status']}")
    print(f"  Runtime: {summary['runtime']['final_status']}")
    print(f"  Broadcast: {summary['runtime']['broadcast_attempted']}")
    if summary["runtime"]["transaction_hash"]:
        print(f"  Transaction: {summary['runtime']['transaction_hash']}")
    print(f"  Success: {summary['success']}")
    print(f"  Summary artifact: {output.relative_to(ROOT)}")
    return 0 if summary["success"] else 10


if __name__ == "__main__":
    raise SystemExit(main())
