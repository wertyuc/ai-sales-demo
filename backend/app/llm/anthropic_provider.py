"""Anthropic Messages API provider (official SDK).

The SDK is imported lazily so that a missing package or an unset key can never
break application startup — the factory falls back to the deterministic provider
and the UI reports the degradation instead of erroring out.
"""
from __future__ import annotations

import json
import logging

from ..config import settings
from .base import LLMProvider, LLMResult, ReplyContext

log = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "", base_url: str = "") -> None:
        self.api_key = api_key
        self.model = model or settings.anthropic_model
        self.base_url = base_url or ""
        self._client = None
        self._error = ""

    # --- client ------------------------------------------------------------

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic  # imported lazily on purpose
        except ImportError as exc:  # pragma: no cover - depends on the image
            self._error = f"anthropic sdk missing: {exc}"
            return None
        kwargs = {"api_key": self.api_key, "timeout": settings.llm_timeout_seconds}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        try:
            self._client = anthropic.Anthropic(**kwargs)
        except Exception as exc:  # pragma: no cover
            self._error = str(exc)
            return None
        return self._client

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    # --- generation --------------------------------------------------------

    def generate(self, ctx: ReplyContext) -> LLMResult:
        elapsed = self._timer()
        client = self._get_client()
        if client is None:
            return LLMResult("", self.name, self.model, elapsed(), self._error, degraded=True)

        payload = [{"role": m.role, "content": m.content} for m in ctx.messages] or [
            {"role": "user", "content": "..."}
        ]
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=ctx.max_tokens,
                system=ctx.system,
                messages=payload,
            )
        except Exception as exc:
            log.warning("anthropic generate failed: %s", exc)
            return LLMResult("", self.name, self.model, elapsed(), str(exc), degraded=True)

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
        if not text:
            return LLMResult("", self.name, self.model, elapsed(), "empty response", degraded=True)
        return LLMResult(text, self.name, self.model, elapsed())

    # --- structured extraction --------------------------------------------

    def extract(self, system: str, text: str, schema: dict) -> dict:
        client = self._get_client()
        if client is None:
            return {}
        tool = {
            "name": "record_qualification",
            "description": "Записать извлечённые параметры квалификации клиента.",
            "input_schema": schema,
        }
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=800,
                system=system,
                messages=[{"role": "user", "content": text}],
                tools=[tool],
                tool_choice={"type": "tool", "name": "record_qualification"},
            )
        except Exception as exc:
            log.warning("anthropic extract failed: %s", exc)
            return {}
        for block in response.content:
            if getattr(block, "type", "") == "tool_use":
                data = block.input
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        return {}
                return data or {}
        return {}
