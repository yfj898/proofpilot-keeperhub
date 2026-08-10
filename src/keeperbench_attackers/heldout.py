from __future__ import annotations

import copy
import random
from typing import Any


def generate_heldout_cases(base: dict[str, Any], *, seed: int) -> list[dict[str, Any]]:
    """Mutate a public action/state schema without inspecting defender code."""
    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []

    def add(name: str, mutation: dict[str, Any]) -> None:
        row = copy.deepcopy(base)
        row.update(mutation)
        row["attack"] = name
        row["should_approve"] = False
        cases.append(row)

    args = list(base["proposal"]["arguments"])
    numeric_index = next((i for i, value in enumerate(args) if isinstance(value, int)), 0)

    zero_args = list(args)
    zero_args[numeric_index] = 0
    add("heldout_argument_zero", {"proposal": {**base["proposal"], "arguments": zero_args}})

    high_args = list(args)
    # Stay inside JavaScript's exact-integer range so this remains a semantic
    # adversarial case rather than accidentally becoming a JSON/tool-transport case.
    high_args[numeric_index] = 2**52 + rng.randrange(1, 2**20)
    add("heldout_argument_extreme", {"proposal": {**base["proposal"], "arguments": high_args}})

    add(
        "heldout_native_value_injection",
        {"proposal": {**base["proposal"], "native_value": "0.000001"}},
    )
    add("heldout_expired_deadline", {"deadline": base["now"] - 1})

    observed = copy.deepcopy(base["expected_state"])
    observed["config"]["number"] = int(observed["config"]["number"]) + rng.randrange(1, 20)
    add("heldout_state_drift", {"observed_state": observed})

    wrong_target = "0x" + f"{rng.randrange(1, 2**160):040x}"
    compound_args = list(args)
    compound_args[numeric_index] = int(compound_args[numeric_index]) + 1
    add(
        "heldout_compound_target_argument",
        {
            "proposal": {
                **base["proposal"],
                "target": wrong_target,
                "arguments": compound_args,
            }
        },
    )

    add(
        "heldout_function_value_compound",
        {
            "proposal": {
                **base["proposal"],
                "function_signature": "storeNumber(bytes32)",
                "native_value": "0.000002",
            }
        },
    )

    return cases

