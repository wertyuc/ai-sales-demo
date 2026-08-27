"""Provider selection and safe fallback.

`get_provider()` honours LLM_PROVIDER, but every real provider is wrapped so that
a network failure degrades to the deterministic renderer instead of surfacing an
error to the customer.  Adding a real model to this demo is one env variable.
"""
from __future__ import annotations

from ..config import settings
from .anthropic_provider import AnthropicProvider
from .base import LLMProvider, LLMResult, ReplyContext
from .demo import DemoProvider
from .openai_provider import OpenAICompatibleProvider

_demo = DemoProvider()


class FallbackProvider(LLMProvider):
    """Primary provider with the deterministic renderer as a safety net."""

    def __init__(self, primary: LLMProvider) -> None:
        self.primary = primary
        self.name = primary.name
        self.model = primary.model

    @property
    def available(self) -> bool:
        return self.primary.available

    def generate(self, ctx: ReplyContext) -> LLMResult:
        result = self.primary.generate(ctx)
        if result.text and not result.degraded:
            return result
        fallback = _demo.generate(ctx)
        fallback.degraded = True
        fallback.error = result.error or "provider returned no text"
        fallback.provider = f"{self.primary.name}→demo"
        return fallback

    def extract(self, system: str, text: str, schema: dict) -> dict:
        return self.primary.extract(system, text, schema)


def _build() -> LLMProvider:
    choice = (settings.llm_provider or "auto").lower()

    if choice in ("demo", "none", "off"):
        return _demo
    if choice == "anthropic" or (choice == "auto" and settings.anthropic_api_key):
        if settings.anthropic_api_key:
            return FallbackProvider(
                AnthropicProvider(
                    settings.anthropic_api_key,
                    settings.anthropic_model,
                    settings.anthropic_base_url,
                )
            )
    if choice == "openai" or (choice == "auto" and settings.openai_api_key):
        if settings.openai_api_key:
            return FallbackProvider(
                OpenAICompatibleProvider(
                    settings.openai_api_key, settings.openai_model, settings.openai_base_url
                )
            )
    return _demo


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = _build()
    return _provider


def reset_provider() -> None:
    """Used by tests and by the Control Center after an env reload."""
    global _provider
    _provider = None


def provider_info() -> dict:
    provider = get_provider()
    is_demo = provider.name == "demo"
    return {
        "provider": provider.name,
        "model": provider.model,
        "mode": "deterministic" if is_demo else "live",
        "configured": not is_demo,
        "note": (
            "Детерминированный demo-провайдер: ответы формируются из плана backend. "
            "Добавьте ANTHROPIC_API_KEY в .env, чтобы подключить реальную модель."
            if is_demo
            else "Подключена реальная модель; при сбое ответ формирует demo-провайдер."
        ),
    }
