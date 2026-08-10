from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.proof_bundle import (  # noqa: E402
    VERIFICATION_LEVEL_L2_EFFECT,
    build_execution_trace_v2,
    build_intent_proof_bundle,
    verify_execution_trace_v2,
    verify_intent_proof_bundle,
)


class ProofBundleTests(unittest.TestCase):
    def test_bundle_is_verified_only_when_all_checks_pass(self) -> None:
        bundle = build_intent_proof_bundle(
            intent_id="i1",
            chain_id="84532",
            target="0x" + "1" * 40,
            mandate={},
            proposal={},
            pre_state={},
            simulation={},
            keeperhub_execution={},
            independent_receipt={},
            post_state={},
            checks={"intent": True, "postcondition": True},
            created_at="2026-08-08T00:00:00+00:00",
        )
        self.assertTrue(bundle["verified"])
        self.assertEqual(len(bundle["sha256"]), 64)
        self.assertTrue(verify_intent_proof_bundle(bundle))

    def test_failed_check_marks_bundle_unverified(self) -> None:
        bundle = build_intent_proof_bundle(
            intent_id="i2",
            chain_id="84532",
            target="0x" + "1" * 40,
            mandate={},
            proposal={},
            pre_state={},
            simulation={},
            keeperhub_execution={},
            independent_receipt={},
            post_state={},
            checks={"intent": True, "postcondition": False},
            created_at="2026-08-08T00:00:00+00:00",
        )
        self.assertFalse(bundle["verified"])

    def test_tampering_breaks_digest(self) -> None:
        bundle = build_intent_proof_bundle(
            intent_id="i3",
            chain_id="84532",
            target="0x" + "1" * 40,
            mandate={},
            proposal={},
            pre_state={"number": 1},
            simulation={"success": True},
            keeperhub_execution={"status": "completed"},
            independent_receipt={"status": "0x1"},
            post_state={"number": 20},
            checks={"intent": True},
            created_at="2026-08-08T00:00:00+00:00",
        )
        bundle["post_state"]["number"] = 200
        self.assertFalse(verify_intent_proof_bundle(bundle))

    def test_v2_verified_requires_execution_receipt_and_postcondition(self) -> None:
        trace = build_execution_trace_v2(
            user_intent="Set Aave E-Mode to 1",
            intent_ir={"action": {"function_signature": "setUserEMode(uint8)"}},
            intent_commitment="a" * 64,
            proposal={"function_signature": "setUserEMode(uint8)", "arguments": [1]},
            intent_assurance={"passed": True, "checks": []},
            pre_state={"aave": {"user_emode": 0}},
            keeperhub_simulation={"success": True, "wouldRevert": False},
            keeperhub_execution={"terminal_check": {"passed": True}},
            independent_receipt={"passed": True},
            post_state={"aave": {"user_emode": 1}},
            postcondition_check={"passed": True},
            final_status="VERIFIED",
            broadcast_attempted=True,
            trace_id="pp_test_verified",
            created_at="2026-08-09T00:00:00+00:00",
        )
        self.assertTrue(verify_execution_trace_v2(trace))
        self.assertEqual(trace["final_status"], "VERIFIED")
        self.assertEqual(len(trace["proposal"]["sha256"]), 64)

    def test_v2_refuses_unverified_verified_claim(self) -> None:
        with self.assertRaises(ValueError):
            build_execution_trace_v2(
                user_intent="Set Aave E-Mode to 1",
                intent_ir={},
                intent_commitment="a" * 64,
                proposal={},
                intent_assurance={"passed": True},
                pre_state={},
                keeperhub_simulation={"success": True, "wouldRevert": False},
                keeperhub_execution={"terminal_check": {"passed": True}},
                independent_receipt={"passed": True},
                postcondition_check={"passed": False},
                final_status="VERIFIED",
                broadcast_attempted=True,
            )

    def test_v2_blocked_trace_cannot_claim_broadcast(self) -> None:
        with self.assertRaises(ValueError):
            build_execution_trace_v2(
                user_intent="Set Aave E-Mode to 1",
                intent_ir={},
                intent_commitment="a" * 64,
                proposal={},
                intent_assurance={"passed": False},
                pre_state={},
                keeperhub_simulation={},
                final_status="BLOCKED",
                broadcast_attempted=True,
            )

    def test_v2_prewrite_terminal_states_cannot_claim_broadcast(self) -> None:
        for final_status in ("SIMULATED", "SIMULATION_FAILED"):
            with self.subTest(final_status=final_status), self.assertRaises(ValueError):
                build_execution_trace_v2(
                    user_intent="Set Aave E-Mode to 1",
                    intent_ir={},
                    intent_commitment="a" * 64,
                    proposal={},
                    intent_assurance={"passed": True},
                    pre_state={},
                    keeperhub_simulation={"success": final_status == "SIMULATED"},
                    final_status=final_status,
                    broadcast_attempted=True,
                )

    def test_v2_rejects_secret_material(self) -> None:
        with self.assertRaises(ValueError):
            build_execution_trace_v2(
                user_intent="Set Aave E-Mode to 1",
                intent_ir={},
                intent_commitment="a" * 64,
                proposal={},
                intent_assurance={"passed": False},
                pre_state={},
                keeperhub_simulation={},
                provenance={"api_key": "kh_" + "this_must_never_be_written"},
                final_status="BLOCKED",
                broadcast_attempted=False,
            )

    def test_v2_tampering_breaks_digest(self) -> None:
        trace = build_execution_trace_v2(
            user_intent="Set Aave E-Mode to 1",
            intent_ir={},
            intent_commitment="a" * 64,
            proposal={"arguments": [0]},
            intent_assurance={"passed": False},
            pre_state={"aave": {"user_emode": 0}},
            keeperhub_simulation={"success": True, "wouldRevert": False},
            semantic_deviations=["wrong_emode_category"],
            final_status="BLOCKED",
            broadcast_attempted=False,
        )
        trace["proposal"]["action"]["arguments"] = [1]
        self.assertFalse(verify_execution_trace_v2(trace))

    def test_authorization_to_execution_profile_requires_explicit_l2_effect_level(self) -> None:
        base = dict(
            user_intent="Set Aave E-Mode to 1",
            intent_ir={},
            intent_commitment="a" * 64,
            proposal={"arguments": [1]},
            intent_assurance={"passed": True},
            pre_state={"aave": {"user_emode": 0}},
            keeperhub_simulation={"success": True, "wouldRevert": False},
            execution_payload={"commitment_match": True},
            keeperhub_execution={"terminal_check": {"passed": True}},
            independent_receipt={"passed": True},
            execution_binding={"passed": True},
            postcondition_check={"passed": True},
            final_status="VERIFIED",
            broadcast_attempted=True,
            context={"verification_profile": "authorization_to_execution_v1"},
        )
        with self.assertRaises(ValueError):
            build_execution_trace_v2(**base)
        trace = build_execution_trace_v2(
            **base,
            verification_level=VERIFICATION_LEVEL_L2_EFFECT,
        )
        self.assertEqual(trace["verification"]["level"], VERIFICATION_LEVEL_L2_EFFECT)
