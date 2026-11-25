"""Application configuration loaded from environment variables."""

import json
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized settings backed by environment variables and optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="Lyftr AI LLM Chatbot API")
    app_version: str = Field(default="1.0.0")
    debug: bool = Field(default=False)

    # Database
    database_url: str = Field(default="sqlite:///./data/chatbot.db")

    # CORS (comma-separated origins or JSON array string)
    allowed_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173"
    )

    # LLM & LiteLLM gateway settings (no keys hardcoded)
    llm_model: str = Field(default="gemini/gemini-3.1-flash-lite")
    gemini_api_base: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta"
    )
    system_prompt: str = Field(
        default="You are a helpful, concise, and accurate AI assistant."
    )

    # Key pool configuration (supports comma-separated pools or numbered env vars)
    gemini_api_keys: str = Field(default="")
    llm_api_keys: str = Field(default="")
    gemini_api_key: Optional[str] = Field(default=None)
    gemini_api_key_1: Optional[str] = Field(default=None)
    gemini_api_key_2: Optional[str] = Field(default=None)
    gemini_api_key_3: Optional[str] = Field(default=None)
    gemini_api_key_fallback: Optional[str] = Field(default=None)
    openai_api_key: Optional[str] = Field(default=None)
    openai_api_key_fallback: Optional[str] = Field(default=None)
    anthropic_api_key: Optional[str] = Field(default=None)

    # LiteLLM cache settings
    cache_enabled: bool = Field(default=True)
    cache_ttl_seconds: int = Field(default=3600, ge=0)

    # Failure simulation (explicitly opt-in via ENABLE_FAILURE_SIMULATION=true)
    enable_failure_simulation: bool = Field(default=False)

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse ALLOWED_ORIGINS into a clean list of origin strings."""
        raw = self.allowed_origins.strip()
        if not raw:
            return []

        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(origin).strip() for origin in parsed if str(origin).strip()]
            except json.JSONDecodeError:
                pass

        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def api_keys(self) -> list[str]:
        """Collect unique, non-empty configured API keys in priority order."""
        candidates: list[str] = []

        for pool_value in (self.gemini_api_keys, self.llm_api_keys):
            if pool_value:
                candidates.extend(
                    key.strip() for key in pool_value.split(",") if key.strip()
                )

        for single_key in (
            self.gemini_api_key_1,
            self.gemini_api_key_2,
            self.gemini_api_key_3,
            self.gemini_api_key,
            self.gemini_api_key_fallback,
            self.openai_api_key,
            self.openai_api_key_fallback,
            self.anthropic_api_key,
        ):
            if single_key and single_key.strip():
                candidates.append(single_key.strip())

        seen: set[str] = set()
        unique_keys: list[str] = []
        for key in candidates:
            if key not in seen:
                seen.add(key)
                unique_keys.append(key)
        return unique_keys

    @property
    def api_key_pool(self) -> list[tuple[str, str]]:
        """Return configured keys paired with internal identifiers (key_1, key_2, ...)."""
        return [(f"key_{idx}", key) for idx, key in enumerate(self.api_keys, start=1)]

    @property
    def keys_configured(self) -> int:
        """Return total number of distinct configured LLM API keys."""
        return len(self.api_keys)

    @property
    def is_key_pool_ready(self) -> bool:
        """Return True when at least two distinct API keys are configured."""
        return self.keys_configured >= 2


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
