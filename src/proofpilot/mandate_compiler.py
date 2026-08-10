from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal

from .intent_ir import (
    DelegationEnvelope,
    IntentConstraint,
    IntentEnvelope,
    IntentIRAction,
    abi_hash,
    delegation_hash,
    source_hash,
    verify_delegation,
)


@dataclass(frozen=True)
class BindingProfile:
    name: str
    protocol: str
    target: str
    function_signature: str
    abi_json: str = ""
    decimals: int = 0
    argument_prefix: tuple[object, ...] = ()
    argument_suffix: tuple[object, ...] = ()


class CompilationError(ValueError):
    pass


class MandateCompiler:
    """Reference NL->Intent compiler with deterministic binding and provenance.

    A stronger host model may propose the parsed fields, but this binder remains the
    authority for target/function/protocol resolution and delegation containment.
    """

    VERSION = "proofpilot-mandate-compiler/1"

    def __init__(self, profiles: dict[str, BindingProfile]):
        self.profiles = {key.lower(): value for key, value in profiles.items()}

    def compile(
        self,
        text: str,
        *,
        delegation: DelegationEnvelope,
        account: str,
        nonce: int,
        deadline: int | None = None,
        intent_id: str | None = None,
    ) -> IntentEnvelope:
        normalized = " ".join(text.strip().split())
        lower = normalized.lower()
        self._reject_unsupported_control_flow(normalized)
        self._reject_unsupported_deadline(normalized)
        self._validate_chain_scope(normalized)
        self._reject_conflicting_actions(normalized)
        self._reject_conflicting_category_values(normalized)
        emode_requested = self._looks_like_emode(normalized)
        if ("category" in lower or "类别" in normalized or "分类" in normalized) and not emode_requested:
            raise CompilationError(
                "Category language is ambiguous without an explicit Aave E-Mode action."
            )
        if emode_requested:
            amount = self._extract_emode_category(normalized)
            if amount != amount.to_integral_value() or amount < 0 or amount > 255:
                raise CompilationError("Aave E-Mode category must be an integer in [0, 255].")
            category_id = int(amount)
            profile = self._profile("aave_emode")
            action = IntentIRAction(
                protocol=profile.protocol,
                target=profile.target,
                function_signature=profile.function_signature,
                arguments=(category_id,),
            )
            post = (IntentConstraint("aave.user_emode", "eq", category_id),)
            invariants = ()
        elif "aave" in lower and ("supply" in lower or "deposit" in lower or "存入" in normalized):
            amount = self._extract_after_action(normalized, ("supply", "deposit", "存入"))
            profile = self._profile("aave")
            action = IntentIRAction(
                protocol=profile.protocol,
                target=profile.target,
                function_signature=profile.function_signature,
                arguments=profile.argument_prefix + (account,) + profile.argument_suffix,
                native_value=amount,
            )
            post = (IntentConstraint("aave.a_weth_delta", "gte", amount),)
            invariants = (IntentConstraint("aave.variable_debt_delta", "eq", Decimal("0")),)
        elif "transfer" in lower or "send" in lower or "转" in normalized:
            amount = self._extract_after_action(normalized, ("transfer", "send", "转"))
            recipient_match = re.search(r"0x[a-fA-F0-9]{40}", normalized)
            if not recipient_match:
                raise CompilationError("ERC20 transfer intent requires an explicit recipient address.")
            profile = self._profile("erc20")
            recipient = recipient_match.group(0)
            raw_amount = int(amount * (Decimal(10) ** profile.decimals))
            action = IntentIRAction(
                protocol=profile.protocol,
                target=profile.target,
                function_signature=profile.function_signature,
                arguments=(recipient, raw_amount),
            )
            post = (IntentConstraint("erc20.recipient_delta", "gte", raw_amount),)
            invariants = ()
        elif "set" in lower or "设置" in normalized or "设为" in normalized:
            amount = self._extract_after_action(normalized, ("set", "设置", "设为"))
            profile = self._profile("storage")
            action = IntentIRAction(
                protocol=profile.protocol,
                target=profile.target,
                function_signature=profile.function_signature,
                arguments=(int(amount),),
            )
            post = (IntentConstraint("config.number", "eq", int(amount)),)
            invariants = ()
        else:
            raise CompilationError("Intent is ambiguous or unsupported by the registered profiles.")

        envelope = IntentEnvelope(
            intent_id=intent_id or f"intent-{uuid.uuid4().hex[:16]}",
            source_text=normalized,
            action=action,
            nonce=nonce,
            deadline=deadline,
            postconditions=post,
            invariants=invariants,
            source_text_hash=source_hash(normalized),
            compiler_version=self.VERSION,
            abi_hash=abi_hash(profile.abi_json) if profile.abi_json else "",
            parent_delegation_hash=delegation_hash(delegation),
            metadata={
                "binding_profile": profile.name,
                "forbidden_effects": (
                    ["aave.collateral_configuration"]
                    if profile.name == "aave_emode"
                    else []
                ),
            },
        )
        decision = verify_delegation(delegation, envelope)
        if not decision.passed:
            raise CompilationError("; ".join(decision.reasons))
        return envelope

    def _profile(self, name: str) -> BindingProfile:
        try:
            return self.profiles[name]
        except KeyError as exc:
            raise CompilationError(f"No binding profile registered for {name!r}.") from exc

    @staticmethod
    def _extract_amount(text: str) -> Decimal:
        matches = re.findall(r"(?<![A-Za-z0-9])([0-9]+(?:\.[0-9]+)?)(?![A-Za-z0-9])", text)
        if not matches:
            raise CompilationError("Intent does not contain a numeric amount/value.")
        return Decimal(matches[0])

    @classmethod
    def _extract_emode_category(cls, text: str) -> Decimal:
        """Extract one unambiguous E-Mode category, never an unrelated chain/deadline value."""

        lower = text.lower()
        if re.search(
            r"(?:e[- ]?mode|emode|e mode|效率模式)[^.;]{0,48}\bfrom\s+\d+[^.;]{0,24}\bto\s+\d+",
            lower,
        ):
            raise CompilationError(
                "Aave E-Mode transition language contains multiple category values; "
                "state the desired final category explicitly."
            )
        if re.search(
            r"(?:do\s+not|don't|never|不要|别)[^.;]{0,64}(?:e[- ]?mode|emode|category|类别)[^.;]{0,32}\d+",
            lower,
        ):
            raise CompilationError(
                "Negated E-Mode/category numbers are not accepted by the bounded compiler."
            )

        explicit = re.findall(
            r"(?:category(?:\s*id)?|类别|分类)[^0-9]{0,24}([0-9]+(?:\.[0-9]+)?)",
            text,
            flags=re.IGNORECASE,
        )
        distinct_explicit = {Decimal(value) for value in explicit}
        if len(distinct_explicit) > 1:
            raise CompilationError("Aave E-Mode intent contains conflicting category ids.")
        if len(distinct_explicit) == 1:
            return next(iter(distinct_explicit))

        patterns = (
            r"(?:e[- ]?mode|emode|效率模式)[^0-9]{0,48}(?:to|为|设为)?[^0-9]{0,24}([0-9]+(?:\.[0-9]+)?)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return Decimal(match.group(1))
        raise CompilationError("Aave E-Mode intent requires an explicit category id.")

    @staticmethod
    def _reject_unsupported_control_flow(text: str) -> None:
        """Fail closed on conditional/branching NL the bounded compiler cannot model."""

        lower = text.lower()
        conditional_patterns = (
            r"\bunless\b",
            r"\bonly\s+if\b",
            r"\bprovided\s+(?:that\s+)?",
            r"\bif\s+[^,.;]+",
            r"如果",
            r"除非",
            r"只在.+(?:时|情况下)",
        )
        if any(re.search(pattern, lower) for pattern in conditional_patterns):
            raise CompilationError(
                "Conditional/branching natural-language intents are unsupported by this bounded compiler."
            )

    @staticmethod
    def _looks_like_emode(text: str) -> bool:
        lower = text.lower()
        return any(
            marker in lower
            for marker in ("e-mode", "emode", "e mode", "效率模式")
        )

    @staticmethod
    def _reject_unsupported_deadline(text: str) -> None:
        """Reject time/deadline language until it can be represented in Intent IR."""

        lower = text.lower()
        deadline_patterns = (
            r"\bdeadline\b",
            r"\bno\s+later\s+than\b",
            r"\buntil\b",
            r"\bbefore\s+\d",
            r"\bby\s+\d",
            r"截止",
            r"\d[^,.;]{0,16}之前",
        )
        if any(re.search(pattern, lower) for pattern in deadline_patterns):
            raise CompilationError(
                "Deadline/time semantics are unsupported by this bounded compiler."
            )

    @staticmethod
    def _validate_chain_scope(text: str) -> None:
        """Consume the only supported explicit chain or reject conflicting scope."""

        lower = text.lower()
        chain_ids = re.findall(r"\bchain(?:\s*id)?\s*(?:=|:)?\s*([0-9]+)\b", lower)
        if any(chain_id != "84532" for chain_id in chain_ids):
            raise CompilationError("Only Base Sepolia chain 84532 is supported.")
        if "mainnet" in lower or re.search(r"\bethereum\b", lower):
            raise CompilationError("Mainnet/Ethereum chain scope is unsupported; use Base Sepolia.")
        if "sepolia" in lower and "base sepolia" not in lower:
            raise CompilationError("Only Base Sepolia, not another Sepolia network, is supported.")
        if re.search(r"\bchain\b", lower) and not chain_ids and "base sepolia" not in lower:
            raise CompilationError("Explicit chain language must bind to Base Sepolia chain 84532.")

    @classmethod
    def _reject_conflicting_actions(cls, text: str) -> None:
        lower = text.lower()
        emode = cls._looks_like_emode(text)
        families = set()
        if emode:
            families.add("aave_emode")
        if "aave" in lower and any(marker in lower for marker in ("supply", "deposit", "存入")):
            families.add("aave_supply")
        if any(marker in lower for marker in ("transfer", "send", "转")):
            families.add("erc20_transfer")
        if not emode and any(marker in lower for marker in ("set", "设置", "设为")):
            families.add("storage_set")
        if len(families) > 1:
            raise CompilationError("Intent contains multiple or conflicting action families.")

    @staticmethod
    def _reject_conflicting_category_values(text: str) -> None:
        explicit = re.findall(
            r"(?:category(?:\s*id)?|类别|分类)[^0-9]{0,24}([0-9]+(?:\.[0-9]+)?)",
            text,
            flags=re.IGNORECASE,
        )
        if len({Decimal(value) for value in explicit}) > 1:
            raise CompilationError("Aave E-Mode intent contains conflicting category ids.")

    @classmethod
    def _extract_after_action(cls, text: str, keywords: tuple[str, ...]) -> Decimal:
        """Prefer the numeric value semantically attached to the action keyword."""

        lower = text.lower()
        candidates: list[tuple[int, str]] = []
        for keyword in keywords:
            index = lower.rfind(keyword.lower())
            if index < 0:
                continue
            tail = text[index + len(keyword) : index + len(keyword) + 96]
            match = re.search(
                r"(?<![A-Za-z0-9])([0-9]+(?:\.[0-9]+)?)(?![A-Za-z0-9])",
                tail,
            )
            if match:
                candidates.append((index, match.group(1)))
        if candidates:
            _, value = max(candidates, key=lambda item: item[0])
            return Decimal(value)
        return cls._extract_amount(text)
