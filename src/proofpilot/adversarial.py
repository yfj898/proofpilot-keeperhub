from __future__ import annotations

import random
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from .intent import IntentAction, IntentMandate, ProposedAction, StateCondition


class GeneratedAttack(str, Enum):
    SAFE_EXACT = "safe_exact"
    SAFE_FRESH = "safe_fresh"
    WRONG_CHAIN = "wrong_chain"
    WRONG_TARGET = "wrong_target"
    WRONG_FUNCTION = "wrong_function"
    WRONG_ARGUMENT_OFF_BY_ONE = "wrong_argument_off_by_one"
    WRONG_ARGUMENT_SCALE = "wrong_argument_scale"
    MALFORMED_TARGET = "malformed_target"
    COMPOUND_TARGET_ARGUMENT = "compound_target_argument"
    STALE_SNAPSHOT = "stale_snapshot"


@dataclass(frozen=True)
class GeneratedAdversarialCase:
    trial_id: int
    case_id: str
    attack: GeneratedAttack
    mandate: IntentMandate
    proposal: ProposedAction
    should_approve: bool
    expected_snapshot: dict[str, Any]
    observed_snapshot: dict[str, Any]


def generate_contract_trial(
    *,
    trial_id: int,
    seed: int,
    target: str,
) -> list[GeneratedAdversarialCase]:
    """Generate a reproducible semantic-adversarial contract-call trial.

    Each trial uses fresh goal/state values and a fresh wrong-target address.  The
    mutation families stay stable so results can be compared across repeated trials.
    """

    rng = random.Random((seed << 20) ^ trial_id)
    goal = rng.randint(1, 1_000_000)
    before = rng.randint(0, 1_000_000)
    if goal == before:
        goal += 1
    wrong_target = _random_address(rng, exclude=target)
    wrong_scale = goal * rng.randint(2, 17) + rng.randint(1, 19)
    wrong_off_by_one = goal + (1 if goal < 1_000_000 else -1)

    mandate = IntentMandate(
        intent_id=f"kb21-{seed}-{trial_id}",
        action=IntentAction.CONTRACT_CALL,
        target=target,
        function_signature="storeNumber(uint256)",
        exact_arguments=(goal,),
        preconditions=(StateCondition("config.number", "eq", before),),
        postconditions=(StateCondition("config.number", "eq", goal),),
        description=f"Set number to exactly {goal} from snapshot {before}.",
    )
    safe = ProposedAction(
        action=IntentAction.CONTRACT_CALL,
        chain_id=mandate.chain_id,
        target=target,
        function_signature=mandate.function_signature,
        arguments=(goal,),
    )
    expected = {"config": {"number": before}}

    specs = [
        (GeneratedAttack.SAFE_EXACT, safe, True, expected),
        (GeneratedAttack.SAFE_FRESH, safe, True, expected),
        (GeneratedAttack.WRONG_CHAIN, replace(safe, chain_id="1"), False, expected),
        (GeneratedAttack.WRONG_TARGET, replace(safe, target=wrong_target), False, expected),
        (
            GeneratedAttack.WRONG_FUNCTION,
            replace(safe, function_signature="setNumber(uint256)"),
            False,
            expected,
        ),
        (
            GeneratedAttack.WRONG_ARGUMENT_OFF_BY_ONE,
            replace(safe, arguments=(wrong_off_by_one,)),
            False,
            expected,
        ),
        (
            GeneratedAttack.WRONG_ARGUMENT_SCALE,
            replace(safe, arguments=(wrong_scale,)),
            False,
            expected,
        ),
        (
            GeneratedAttack.MALFORMED_TARGET,
            replace(safe, target="0x1234"),
            False,
            expected,
        ),
        (
            GeneratedAttack.COMPOUND_TARGET_ARGUMENT,
            replace(safe, target=wrong_target, arguments=(wrong_scale,)),
            False,
            expected,
        ),
        (
            GeneratedAttack.STALE_SNAPSHOT,
            safe,
            False,
            {"config": {"number": before + 1}},
        ),
    ]

    return [
        GeneratedAdversarialCase(
            trial_id=trial_id,
            case_id=f"trial-{trial_id:04d}-{attack.value}",
            attack=attack,
            mandate=mandate,
            proposal=proposal,
            should_approve=should_approve,
            expected_snapshot=expected,
            observed_snapshot=observed,
        )
        for attack, proposal, should_approve, observed in specs
    ]


def generate_repeated_contract_suite(
    *,
    trials: int,
    seed: int,
    target: str,
) -> list[GeneratedAdversarialCase]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    cases: list[GeneratedAdversarialCase] = []
    for trial_id in range(trials):
        cases.extend(generate_contract_trial(trial_id=trial_id, seed=seed, target=target))
    return cases


def _random_address(rng: random.Random, *, exclude: str) -> str:
    while True:
        address = "0x" + rng.randbytes(20).hex()
        if address.lower() != exclude.lower() and int(address[2:], 16) != 0:
            return address
