#!/usr/bin/env python3
"""Fail closed when the public ProofPilot surface contains local credentials/state."""

from __future__ import annotations

import argparse
import re
import stat
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_EXCLUDED_DIRS = frozenset(
    {".git", ".proofpilot", ".pytest_cache", ".venv", "__pycache__", "dist"}
)
REQUIRED_LOCAL_IGNORES = frozenset({".env", ".proofpilot/", "keeperhub-backup-codes.txt"})
SECRET_PATTERNS = (
    (re.compile(rb"\bkh_[A-Za-z0-9_-]{20,}\b"), "KeeperHub API-key-shaped value"),
    (re.compile(rb"\bnvapi-[A-Za-z0-9_-]{20,}\b"), "NVIDIA API-key-shaped value"),
    (
        re.compile(
            rb"(?i)(?:private[_ -]?key|seed(?:[_ -]?phrase)?|mnemonic)"
            rb"\s*[:=]\s*['\"]?(?:0x)?[0-9a-f]{64}\b"
        ),
        "private-key-shaped assignment",
    ),
)


@dataclass(frozen=True)
class Finding:
    path: str
    reason: str


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _is_forbidden_secret_filename(path: Path) -> str | None:
    name = path.name.lower()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "forbidden .env file"
    if name.endswith(".sqlite3"):
        return "forbidden SQLite journal/database"
    if "backup" in name and "code" in name:
        return "backup-code-like filename"
    if any(marker in name for marker in ("mnemonic", "seed-phrase", "seed_phrase", "private-key")):
        return "mnemonic/private-key-like filename"
    return None


def _ignored_local_state_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    ignore_path = root / ".gitignore"
    ignore_lines = set()
    if ignore_path.is_file():
        ignore_lines = {
            line.strip()
            for line in ignore_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    for required in sorted(REQUIRED_LOCAL_IGNORES):
        if required not in ignore_lines:
            findings.append(Finding(".gitignore", f"missing required ignore: {required}"))

    env_path = root / ".env"
    if env_path.exists() and (not env_path.is_file() or _mode(env_path) != 0o600):
        findings.append(Finding(".env", "local .env must be a regular file with mode 0600"))

    journal_dir = root / ".proofpilot"
    if journal_dir.exists() and (not journal_dir.is_dir() or _mode(journal_dir) != 0o700):
        findings.append(Finding(".proofpilot", "local journal directory must have mode 0700"))
    if journal_dir.is_dir():
        for database in journal_dir.glob("*.sqlite3"):
            if not database.is_file() or _mode(database) != 0o600:
                findings.append(
                    Finding(_relative(database, root), "local journal database must have mode 0600")
                )
    return findings


def check_tree(root: Path, *, strict_export: bool) -> list[Finding]:
    root = root.resolve()
    if not root.is_dir():
        return [Finding(str(root), "scan root is not a directory")]

    findings = [] if strict_export else _ignored_local_state_findings(root)
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not strict_export and any(part in SOURCE_EXCLUDED_DIRS for part in relative.parts[:-1]):
            continue
        if path.is_symlink():
            findings.append(Finding(relative.as_posix(), "symlink is not allowed in public export"))
            continue
        if not path.is_file():
            continue

        reason = _is_forbidden_secret_filename(path)
        is_allowed_local_env = not strict_export and relative.as_posix() == ".env"
        is_allowed_local_journal = (
            not strict_export
            and len(relative.parts) == 2
            and relative.parts[0] == ".proofpilot"
            and path.suffix == ".sqlite3"
        )
        if reason and not is_allowed_local_env and not is_allowed_local_journal:
            findings.append(Finding(relative.as_posix(), reason))
            continue
        if is_allowed_local_env or is_allowed_local_journal:
            continue

        try:
            data = path.read_bytes()
        except OSError:
            findings.append(Finding(relative.as_posix(), "file could not be inspected"))
            continue
        if b"\0" in data:
            continue
        for pattern, pattern_reason in SECRET_PATTERNS:
            if pattern.search(data):
                findings.append(Finding(relative.as_posix(), pattern_reason))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--strict-export",
        action="store_true",
        help="Treat every local .env/database as forbidden, for an already-created public export.",
    )
    args = parser.parse_args()
    findings = check_tree(args.root, strict_export=args.strict_export)
    if findings:
        for finding in findings:
            print(f"FAIL {finding.path}: {finding.reason}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
