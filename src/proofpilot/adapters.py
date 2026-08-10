from __future__ import annotations

from typing import Any, Protocol

from .intent import IntentMandate, ProposedAction
from .models import VerificationResult
from .reader import BaseSepoliaReader


class OutcomeAdapter(Protocol):
    name: str

    def read_state(self, reader: BaseSepoliaReader, account: str) -> dict[str, Any]: ...
    def verify_outcome(
        self,
        mandate: IntentMandate,
        pre: dict[str, Any],
        post: dict[str, Any],
    ) -> VerificationResult: ...
    def proposal(self, mandate: IntentMandate) -> ProposedAction: ...


class AdapterRegistry:
    def __init__(self) -> None:
        self._items: dict[str, OutcomeAdapter] = {}

    def register(self, adapter: OutcomeAdapter) -> None:
        self._items[adapter.name] = adapter

    def get(self, name: str) -> OutcomeAdapter:
        return self._items[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._items))

