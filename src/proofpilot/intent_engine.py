from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .execution_binding import canonical_contract_call_payload, execution_payload_sha256
from .intent import IntentAction, IntentMandate, ProposedAction, assure_intent, verify_state_conditions
from .mcp import McpError
from .models import VerificationResult
from .verifier import verify_simulation, verify_simulation_binding


class ContractSimulator(Protocol):
    def simulate_contract_call(
        self,
        *,
        contract_address: str,
        function_name: str,
        function_args: str = "[]",
        abi: str = "",
        value: str = "0",
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class IntentAdmission:
    approved: bool
    intent_check: VerificationResult
    precondition_check: VerificationResult | None = None
    simulation_check: VerificationResult | None = None
    simulation_binding_check: VerificationResult | None = None
    simulation: dict[str, Any] | None = None
    execution_payload: dict[str, Any] | None = None
    execution_payload_sha256: str = ""
    error: str = ""


class IntentAssuranceEngine:
    """Pre-write semantic gate for KeeperHub contract calls."""

    def __init__(self, simulator: ContractSimulator):
        self.simulator = simulator

    def admit_contract_call(
        self,
        mandate: IntentMandate,
        proposal: ProposedAction,
        *,
        pre_state: dict[str, Any],
        abi: str,
        expected_sender: str | None = None,
    ) -> IntentAdmission:
        intent_check = assure_intent(mandate, proposal)
        if not intent_check.passed:
            return IntentAdmission(False, intent_check, error="; ".join(intent_check.reasons))

        if proposal.action != IntentAction.CONTRACT_CALL:
            return IntentAdmission(False, intent_check, error="Contract admission requires contract_call.")

        precondition_check = verify_state_conditions(
            mandate.preconditions,
            pre_state,
            phase="pre",
        )
        if not precondition_check.passed:
            return IntentAdmission(
                False,
                intent_check,
                precondition_check=precondition_check,
                error="; ".join(precondition_check.reasons),
            )

        payload = canonical_contract_call_payload(proposal, abi=abi)
        payload_sha = execution_payload_sha256(payload)
        try:
            simulation = self.simulator.simulate_contract_call(
                contract_address=str(payload["contract_address"]),
                function_name=str(payload["function_name"]),
                function_args=str(payload["function_args"]),
                abi=str(payload["abi"]),
                value=str(payload["value"]),
            )
        except McpError as exc:
            return IntentAdmission(
                False,
                intent_check,
                precondition_check=precondition_check,
                error=str(exc),
            )

        simulation_check = verify_simulation(simulation)
        simulation_binding_check = verify_simulation_binding(
            simulation,
            proposal,
            expected_sender=expected_sender,
        )
        approved = simulation_check.passed and simulation_binding_check.passed
        return IntentAdmission(
            approved,
            intent_check,
            precondition_check=precondition_check,
            simulation_check=simulation_check,
            simulation_binding_check=simulation_binding_check,
            simulation=simulation,
            execution_payload=payload,
            execution_payload_sha256=payload_sha,
            error=(
                ""
                if approved
                else "; ".join((*simulation_check.reasons, *simulation_binding_check.reasons))
            ),
        )

