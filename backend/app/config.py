"""Application settings.

Everything that can differ between the demo laptop and the VPS lives here and is
driven by environment variables.  Defaults are chosen so that `uvicorn app.main:app`
works with zero configuration (SQLite + deterministic demo LLM).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Sales Demo Suite"
    environment: str = "local"

    # --- storage -----------------------------------------------------------
    # Postgres in docker-compose, SQLite when running bare for a quick look.
    database_url: str = "sqlite:///./ai_sales_demo.db"

    # --- auth --------------------------------------------------------------
    admin_username: str = "admin"
    admin_password: str = "demo1234"
    secret_key: str = "dev-only-secret-change-me"
    session_ttl_hours: int = 24

    # --- LLM ---------------------------------------------------------------
    # provider: auto | anthropic | openai | demo
    llm_provider: str = "auto"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    anthropic_base_url: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0
    llm_max_tokens: int = 1200

    # --- demo behaviour ----------------------------------------------------
    seed_on_startup: bool = True
    scheduler_enabled: bool = True
    scheduler_tick_seconds: float = 1.0
    demo_speed: int = 60  # virtual minutes per real second

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
