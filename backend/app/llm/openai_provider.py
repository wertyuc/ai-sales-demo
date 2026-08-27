"""OpenAI-compatible provider.

Talks plain chat-completions over HTTP, so it also covers the many Russian and
self-hosted gateways that expose an OpenAI-shaped endpoint (vLLM, Ollama,
GigaChat proxies, OpenRouter, …).  Point `OPENAI_BASE_URL` at any of them.
"""
from __future__ import annotations

import json
import logging

import httpx

from ..config import settings
from .base import LLMProvider, LLMResult, ReplyContext

log = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "", base_url: str = "") -> None:
        self.api_key = api_key
        self.model = model or settings.openai_model
        self.base_url = (base_url or settings.openai_base_url).rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _post(self, body: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=body
            )
            response.raise_for_status()
            return response.json()

    def generate(self, ctx: ReplyContext) -> LLMResult:
        elapsed = self._timer()
        messages = [{"role": "system", "content": ctx.system}]
        messages += [{"role": m.role, "content": m.content} for m in ctx.messages]
        try:
            data = self._post(
                {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": ctx.max_tokens,
                    "temperature": 0.6,
                }
            )
            text = (data["choices"][0]["message"].get("content") or "").strip()
        except Exception as exc:
            log.warning("openai generate failed: %s", exc)
            return LLMResult("", self.name, self.model, elapsed(), str(exc), degraded=True)
        if not text:
            return LLMResult("", self.name, self.model, elapsed(), "empty response", degraded=True)
        return LLMResult(text, self.name, self.model, elapsed())

    def extract(self, system: str, text: str, schema: dict) -> dict:
        try:
            data = self._post(
                {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                    "max_tokens": 600,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                }
            )
            payload = data["choices"][0]["message"].get("content") or "{}"
            return json.loads(payload)
        except Exception as exc:
            log.warning("openai extract failed: %s", exc)
            return {}
