from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.blind_keeperbench import build_blind_artifact  # noqa: E402


DEFAULT_TARGET = "0x893a327e3714b2780B28C35FfEcb52AfA0157F15"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen held-out KeeperBench.")
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--trials", type=int, default=100)
    args = parser.parse_args()
    artifact = build_blind_artifact(ROOT, target=args.target, seed=args.seed, trials=args.trials)
    print(json.dumps(artifact, indent=2))
    return 0 if not artifact["attacker_imports_defender"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

