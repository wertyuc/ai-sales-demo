"""LLM provider abstraction.

Design note — why there is a `plan` next to `system` / `messages`:

The backend decides *what* must be said (which questions are still open, which
products are genuinely in stock, which price ceiling applies, whether a handoff
is due).  The model only decides *how* to say it.  A real provider receives that
decision as a system prompt; the deterministic demo provider renders the same
decision from templates.  Business behaviour is therefore identical with or
without an API key, and the model is never in a position to invent stock, price
or specifications.
"""
from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # user | assistant
    content: str


@dataclass
class ReplyContext:
    system: str
    messages: list[LLMMessage]
    plan: dict[str, Any] = field(default_factory=dict)
    max_tokens: int = 900


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: int = 0
    error: str = ""
    degraded: bool = False


class LLMProvider(abc.ABC):
    name: str = "base"
    model: str = ""

    @property
    def available(self) -> bool:
        return True

    @abc.abstractmethod
    def generate(self, ctx: ReplyContext) -> LLMResult: ...

    def extract(self, system: str, text: str, schema: dict) -> dict:
        """Optional structured extraction; providers without it return {}."""
        return {}

    @staticmethod
    def _timer():
        start = time.perf_counter()
        return lambda: int((time.perf_counter() - start) * 1000)
