from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.keeperbench import (  # noqa: E402
    default_contract_suite,
    default_transfer_suite,
    run_state_semantics_suite,
    run_keeperbench,
)


TARGET = "0x1111111111111111111111111111111111111111"
WRONG_TARGET = "0x2222222222222222222222222222222222222222"


def main() -> int:
    scenarios = [
        *default_transfer_suite(
            target=TARGET,
            wrong_target=WRONG_TARGET,
            amount=Decimal("0.000001"),
        ),
        *default_contract_suite(target=TARGET, wrong_target=WRONG_TARGET),
    ]
    results, summary = run_keeperbench(scenarios)
    state_results = run_state_semantics_suite()
    payload = {
        "schema": "proofpilot.keeperbench.v1",
        "summary": {
            "total": summary.total,
            "correct": summary.correct,
            "accuracy": summary.accuracy,
            "unsafe_total": summary.unsafe_total,
            "unsafe_approved": summary.unsafe_approved,
            "unsafe_approval_rate": summary.unsafe_approval_rate,
            "safe_total": summary.safe_total,
            "safe_rejected": summary.safe_rejected,
            "safe_rejection_rate": summary.safe_rejection_rate,
        },
        "scenarios": [
            {
                "name": result.scenario.name,
                "kind": result.scenario.kind.value,
                "should_approve": result.scenario.should_approve,
                "approved": result.approved,
                "correct": result.correct,
                "reasons": list(result.reasons),
            }
            for result in results
        ],
        "state_semantics": [
            {
                "name": result.name,
                "kind": result.kind.value,
                "should_pass": result.should_pass,
                "passed": result.passed,
                "correct": result.correct,
                "reasons": list(result.reasons),
            }
            for result in state_results
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0 if summary.correct == summary.total and all(r.correct for r in state_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

