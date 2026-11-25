"""Runtime verification tests for /health readiness, key pool validation, and SQLite DB."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app.config import Settings, get_settings
from app.database import SessionLocal, engine, get_db
from app.main import app
from app.models import Message
from app.schemas import MessageSchema


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Ensure cached settings are cleared before and after each test."""
    get_settings.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_health_fails_readiness_when_no_keys_configured(monkeypatch):
    """GET /health returns 503 when the required 2-key pool is missing."""
    for env_var in (
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
    ):
        monkeypatch.delenv(env_var, raising=False)
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["keys_configured"] == 0
    assert "2 distinct" in payload["detail"]


def test_health_fails_readiness_with_single_or_duplicate_keys(monkeypatch):
    """At least two distinct API keys are required; duplicates count as one."""
    monkeypatch.setenv("LLM_API_KEYS", "dup-key, dup-key")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["keys_configured"] == 1


def test_health_succeeds_with_two_distinct_keys_and_sqlite(monkeypatch):
    """GET /health returns 200 ok only when SQLite is reachable and >=2 distinct keys exist."""
    monkeypatch.setenv("LLM_API_KEYS", "pool-key-a, pool-key-b, pool-key-a")
    monkeypatch.setenv("CACHE_ENABLED", "false")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "keys_configured": 2,
        "cache_enabled": False,
    }


def test_health_fails_when_sqlite_connectivity_fails(monkeypatch):
    """GET /health returns 503 if SQLite SELECT 1 fails."""
    monkeypatch.setenv("GEMINI_API_KEYS", "pool-key-a, pool-key-b")
    get_settings.cache_clear()

    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise OperationalError("SELECT 1", {}, Exception("db down"))

    def _override_broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = _override_broken_db

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["detail"] == "database unavailable"


def test_keys_configured_combines_individual_provider_vars(monkeypatch):
    """keys_configured counts unique keys across GEMINI/LLM/provider key vars."""
    monkeypatch.delenv("LLM_API_KEYS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "provider-key-1")
    monkeypatch.setenv("GEMINI_API_KEY", "provider-key-2")

    settings = Settings(_env_file=None)
    assert settings.keys_configured == 2
    assert settings.is_key_pool_ready is True


def test_cors_allows_configured_origins(monkeypatch):
    """CORSMiddleware returns Access-Control-Allow-Origin for configured origins."""
    monkeypatch.setenv("GEMINI_API_KEYS", "cors-key-1,cors-key-2")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get(
            "/health",
            headers={"Origin": "http://localhost:5173"},
        )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_sqlite_database_connectivity_and_schema():
    """SQLite database connects, auto-creates messages table, and supports CRUD."""
    with TestClient(app):
        with SessionLocal() as db:
            result = db.execute(text("SELECT 1")).scalar_one()
            assert result == 1

        inspector = inspect(engine)
        assert "messages" in inspector.get_table_names()

        column_names = {col["name"] for col in inspector.get_columns("messages")}
        expected_columns = {
            "id",
            "session_id",
            "role",
            "content",
            "metadata",
            "created_at",
        }
        assert expected_columns.issubset(column_names)

        test_session = "phase1-db-verify-session"
        with SessionLocal() as db:
            msg = Message(
                session_id=test_session,
                role="user",
                content="Phase 1 DB connectivity check",
                message_metadata={
                    "resolution_source": "LIVE_INFERENCE",
                    "model": "gemini/gemini-2.5-flash",
                    "latency_ms": 12,
                    "input_tokens": 5,
                    "output_tokens": 7,
                    "key_id": "key_1",
                    "fallback_attempts": 0,
                },
            )
            db.add(msg)
            db.commit()
            db.refresh(msg)

            assert msg.id is not None
            serialized = MessageSchema.model_validate(msg)
            assert serialized.metadata["resolution_source"] == "LIVE_INFERENCE"

            db.delete(msg)
            db.commit()
