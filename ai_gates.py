"""Reusable fast AI classification gates for filter pipelines."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from script_scaffold.search import ai_chat

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateResult:
    """Outcome of a single-item AI gate."""

    keep: bool
    reason: str = ""
    ai_called: bool = False


class FastAiGate(ABC):
    """Single-item boolean AI gate using ``route=fast`` and JSON mode.

    Subclasses implement ``build_prompt`` and ``parse_reply``, and may override
    ``should_skip`` to bypass the AI call for known-good inputs (e.g. a URL shape
    that already identifies a genuine posting).

    ``evaluate()`` calls ``ai_chat``, applies fail-open/closed policy when the
    reply is missing or unparseable, and returns a ``GateResult``.
    """

    route: ClassVar[str] = "fast"
    max_tokens: ClassVar[int] = 64
    reject_reason: ClassVar[str] = "ai_rejected"
    error_reason: ClassVar[str] = "ai_gate_error"

    @abstractmethod
    def build_prompt(self, **ctx) -> str:
        """Build the user prompt from caller-supplied context kwargs."""

    @abstractmethod
    def parse_reply(self, reply: str | None) -> bool | None:
        """Return True to keep, False to reject, None if unparseable."""

    def should_skip(self, **ctx) -> bool:
        """Return True to keep the item without calling the AI."""
        return False

    def evaluate(self, *, fail_open: bool = True, **ctx) -> GateResult:
        """Run the gate and return whether the item should be kept."""
        if self.should_skip(**ctx):
            return GateResult(keep=True)

        reply = ai_chat(
            self.build_prompt(**ctx),
            route=self.route,
            json_mode=True,
            max_tokens=self.max_tokens,
        )
        decision = self.parse_reply(reply)

        if decision is None:
            if fail_open:
                return GateResult(keep=True, ai_called=True)
            return GateResult(keep=False, reason=self.error_reason, ai_called=True)

        if decision:
            return GateResult(keep=True, ai_called=True)
        return GateResult(keep=False, reason=self.reject_reason, ai_called=True)
