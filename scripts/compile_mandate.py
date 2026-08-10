from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proofpilot.aave_adapter import (  # noqa: E402
    AAVE_BASE_SEPOLIA_POOL,
    AAVE_BASE_SEPOLIA_WETH_GATEWAY,
    AAVE_DEPOSIT_ETH_ABI,
)
from proofpilot.intent_ir import DelegationEnvelope  # noqa: E402
from proofpilot.mandate_compiler import BindingProfile, CompilationError, MandateCompiler  # noqa: E402


STORAGE_TARGET = "0x893a327e3714b2780B28C35FfEcb52AfA0157F15"
ERC20_TARGET = "0x60c8a606b2114337b4301bd55b48e33c9d86643e"


def profiles() -> dict[str, BindingProfile]:
    return {
        "storage": BindingProfile("storage-demo", "storage", STORAGE_TARGET, "storeNumber(uint256)"),
        "erc20": BindingProfile("pptt-erc20", "erc20", ERC20_TARGET, "transfer(address,uint256)", decimals=6),
        "aave": BindingProfile(
            "aave-base-sepolia-eth-supply",
            "aave",
            AAVE_BASE_SEPOLIA_WETH_GATEWAY,
            "depositETH(address,address,uint16)",
            AAVE_DEPOSIT_ETH_ABI,
            argument_prefix=(AAVE_BASE_SEPOLIA_POOL,),
            argument_suffix=(0,),
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile natural language into a ProofPilot IntentEnvelope.")
    parser.add_argument("text")
    parser.add_argument("--account", default="0x1111111111111111111111111111111111111111")
    parser.add_argument("--nonce", type=int, default=1)
    parser.add_argument("--deadline", type=int)
    parser.add_argument("--intent-id")
    parser.add_argument("--max-native-value", default="0.001")
    args = parser.parse_args()

    compiler = MandateCompiler(profiles())
    profile_targets = {profile.target for profile in profiles().values()}
    delegation = DelegationEnvelope(
        delegation_id="cli-demo",
        allowed_protocols=frozenset({"storage", "erc20", "aave"}),
        allowed_targets=frozenset(profile_targets),
        allowed_functions=frozenset(profile.function_signature for profile in profiles().values()),
        max_native_value=Decimal(args.max_native_value),
        expires_at=args.deadline,
    )
    try:
        intent = compiler.compile(
            args.text,
            delegation=delegation,
            account=args.account,
            nonce=args.nonce,
            deadline=args.deadline,
            intent_id=args.intent_id,
        )
    except CompilationError as exc:
        print(json.dumps({"compiled": False, "error": str(exc)}, indent=2))
        return 2

    print(
        json.dumps(
            {
                "compiled": True,
                "intent": intent.canonical_dict(),
                "commitment": intent.commitment(),
                "eip712_typed_data": intent.to_eip712_typed_data(),
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

