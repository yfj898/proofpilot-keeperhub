from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_competition_demo import build_summary  # noqa: E402


class CompetitionDemoSummaryTests(unittest.TestCase):
    def _files(self, doctor_payload: dict, trace_payload: dict):
        temp = tempfile.TemporaryDirectory(dir=ROOT)
        base = Path(temp.name)
        doctor = base / "doctor.json"
        trace = base / "trace.json"
        doctor.write_text(json.dumps(doctor_payload), encoding="utf-8")
        trace.write_text(json.dumps(trace_payload), encoding="utf-8")
        return temp, doctor, trace

    def test_observe_summary_requires_simulated_without_broadcast(self) -> None:
        temp, doctor, trace = self._files(
            {"status": "READY", "write_performed": False},
            {
                "final_status": "SIMULATED",
                "broadcast_attempted": False,
                "trace_id": "pp_test",
                "keeperhub": {"execution": {}},
            },
        )
        with temp:
            summary = build_summary(doctor_path=doctor, trace_path=trace, live=False)
            self.assertTrue(summary["success"])

    def test_summary_requires_doctor_to_remain_read_only(self) -> None:
        temp, doctor, trace = self._files(
            {"status": "READY", "write_performed": True},
            {
                "final_status": "SIMULATED",
                "broadcast_attempted": False,
                "trace_id": "pp_test",
                "keeperhub": {"execution": {}},
            },
        )
        with temp:
            summary = build_summary(doctor_path=doctor, trace_path=trace, live=False)
            self.assertFalse(summary["success"])

    def test_live_summary_requires_verified_and_broadcast(self) -> None:
        temp, doctor, trace = self._files(
            {"status": "READY", "write_performed": False},
            {
                "final_status": "VERIFIED",
                "broadcast_attempted": True,
                "trace_id": "pp_test",
                "keeperhub": {"execution": {"transaction_hash": "0xabc"}},
            },
        )
        with temp:
            summary = build_summary(doctor_path=doctor, trace_path=trace, live=True)
            self.assertTrue(summary["success"])
            self.assertEqual(summary["runtime"]["transaction_hash"], "0xabc")


if __name__ == "__main__":
    unittest.main()
