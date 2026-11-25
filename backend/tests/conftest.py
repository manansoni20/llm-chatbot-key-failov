"""Pytest configuration ensuring tests remain isolated from host/Docker .env files."""

import os
from pathlib import Path

import pytest

# Set test DATABASE_URL before importing litellm/app.database so load_dotenv()
# from a parent Docker .env (e.g. sqlite:////data/chatbot.db) cannot hijack tests.
_TEST_DB_PATH = Path(__file__).resolve().parent.parent / ".pytest_cache" / "pytest_foundation.db"
_TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

_HOST_ENV_KEYS_TO_ISOLATE = (
    "GEMINI_API_KEYS",
    "LLM_API_KEYS",
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_1",
    "GEMINI_API_KEY_2",
    "GEMINI_API_KEY_3",
    "GEMINI_API_KEY_FALLBACK",
    "OPENAI_API_KEY",
    "OPENAI_API_KEY_FALLBACK",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_BASE",
    "LLM_MODEL",
    "CACHE_ENABLED",
    "ENABLE_FAILURE_SIMULATION",
    "SYSTEM_PROMPT",
)


@pytest.fixture(autouse=True)
def isolate_env_from_host_dotenv(monkeypatch):
    """Prevent keys or flags loaded by litellm's dotenv from leaking into tests."""
    for var in _HOST_ENV_KEYS_TO_ISOLATE:
        monkeypatch.delenv(var, raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
