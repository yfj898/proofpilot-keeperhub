#!/usr/bin/env python3
"""Create an allowlisted ProofPilot public tree and verify it before use."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from check_submission_hygiene import check_tree


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    ".env.example",
    ".gitignore",
    "AGENTS.md",
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "docs/AI_AGENT_RUNTIME.md",
    "docs/ARCHITECTURE.md",
    "docs/COMPETITION_DEMO.md",
    "docs/DORAHACKS_SUBMISSION.md",
    "docs/EXTERNAL_REDTEAM_AAVE.md",
    "docs/FINAL_SUBMISSION_AUDIT.md",
    "docs/FINAL_VIDEO_SCRIPT.md",
    "docs/JUDGE_BRIEF.md",
    "docs/OFFICIAL_KEEPERHUB_MCP_RUNTIME.md",
    "docs/SOURCES.md",
    "docs/VIDEO_RECORDING_CHECKLIST.md",
    "artifacts/demo/proofpilot-agent-live-20260809.json",
    "artifacts/demo/proofpilot-agent-live-cleanup-20260809.json",
    "artifacts/demo/proofpilot-agent-simulation-20260809.json",
    "artifacts/demo/proofpilot-attack-validation-trace-v2.json",
    "artifacts/demo/proofpilot-autonomous-cleanup.json",
    "artifacts/demo/proofpilot-autonomous-live.json",
    "artifacts/demo/proofpilot-five-fixes-cleanup.json",
    "artifacts/demo/proofpilot-five-fixes-live.json",
    "artifacts/demo/proofpilot-five-fixes-observe.json",
    "artifacts/keeperbench/external-redteam-aave-formal-20260809-25x2-final-submission.json",
    "artifacts/reliability/reliability-report.json",
    "artifacts/runtime/competition-demo-doctor.json",
    "artifacts/runtime/keeperhub-mcp-check.json",
)
PUBLIC_DIRECTORIES = ("contracts", "scripts", "src", "tests")
SKIPPED_PARTS = frozenset({".pytest_cache", "__pycache__"})
SKIPPED_SUFFIXES = frozenset({".pyc", ".pyo"})


def _copy_public_directory(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in SKIPPED_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() in SKIPPED_SUFFIXES:
            continue
        if path.is_symlink():
            raise RuntimeError(f"Public export refuses symlink: {path}")
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def create_export(source_root: Path, output: Path) -> None:
    source_root = source_root.resolve()
    output = output.resolve()
    if not source_root.is_dir():
        raise RuntimeError("Source root is not a directory")
    if output.exists():
        raise RuntimeError("Output already exists; choose a new empty path")
    if output == source_root or source_root in output.parents:
        raise RuntimeError("Output must be outside the source tree")

    source_findings = check_tree(source_root, strict_export=False)
    if source_findings:
        rendered = "; ".join(f"{item.path}: {item.reason}" for item in source_findings)
        raise RuntimeError(f"Source hygiene failed: {rendered}")

    output.mkdir(parents=True)
    for relative in PUBLIC_FILES:
        source = source_root / relative
        if source.is_symlink():
            raise RuntimeError(f"Public export refuses symlink: {source}")
        if source.is_file():
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for name in PUBLIC_DIRECTORIES:
        source = source_root / name
        if source.is_dir():
            _copy_public_directory(source, output / name)

    export_findings = check_tree(output, strict_export=True)
    if export_findings:
        rendered = "; ".join(f"{item.path}: {item.reason}" for item in export_findings)
        raise RuntimeError(f"Export hygiene failed: {rendered}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New output directory outside the project tree")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        create_export(args.source_root, args.output)
    except RuntimeError as exc:
        print(f"FAIL {exc}")
        return 1
    print(f"PASS {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
