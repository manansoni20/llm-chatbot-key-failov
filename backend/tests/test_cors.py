"""Automated tests for CORS preflight, origin normalization, and deployed frontend origin."""

import litellm
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import create_app

DEPLOYED_FRONTEND_ORIGIN = "https://lyftr-chatbot-frontend-i3xe.onrender.com"


@pytest.fixture
def cors_client(tmp_path, monkeypatch):
    """Build a fresh FastAPI app and isolated SQLite DB to test CORS settings."""
    db_file = tmp_path / "test_cors.db"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
        future=True,
    )
    Base.metadata.create_all(bind=test_engine)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv("LLM_API_KEYS", "cors-test-key-1,cors-test-key-2")
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    get_settings.cache_clear()
    litellm.cache = None

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, app

    app.dependency_overrides.clear()
    litellm.cache = None
    get_settings.cache_clear()
    test_engine.dispose()


@pytest.mark.parametrize(
    "origin",
    [
        DEPLOYED_FRONTEND_ORIGIN,
        "http://localhost:3000",
        "http://localhost:5173",
    ],
)
def test_options_preflight_chat_allows_deployed_and_local_origins(cors_client, origin):
    """OPTIONS /chat preflight returns 200 for exact deployed and local frontend origins."""
    client, _ = cors_client
    resp = client.options(
        "/chat",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, accept",
        },
    )

    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin
    assert resp.headers.get("access-control-allow-credentials") == "true"

    allowed_methods = {
        m.strip().upper()
        for m in resp.headers.get("access-control-allow-methods", "").split(",")
        if m.strip()
    }
    assert {"GET", "POST", "OPTIONS"}.issubset(allowed_methods)

    allowed_headers = {
        h.strip().lower()
        for h in resp.headers.get("access-control-allow-headers", "").split(",")
        if h.strip()
    }
    assert {"content-type", "accept"}.issubset(allowed_headers)


def test_options_preflight_allows_simulate_failure_header(cors_client):
    """OPTIONS /chat permits X-Simulate-Failure when requested."""
    client, _ = cors_client
    resp = client.options(
        "/chat",
        headers={
            "Origin": DEPLOYED_FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, accept, x-simulate-failure",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == DEPLOYED_FRONTEND_ORIGIN


def test_options_preflight_rejects_disallowed_origin(cors_client):
    """OPTIONS /chat rejects unknown origins with 400 and never uses wildcard '*'."""
    client, _ = cors_client
    resp = client.options(
        "/chat",
        headers={
            "Origin": "https://untrusted.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, accept",
        },
    )
    assert resp.status_code == 400
    assert "Disallowed CORS origin" in resp.text
    assert resp.headers.get("access-control-allow-origin") is None


def test_allowed_origins_normalizes_trailing_slash_quotes_and_excludes_wildcard(monkeypatch):
    """ALLOWED_ORIGINS strips trailing slashes/quotes and drops '*' when credentials are enabled."""
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        f' "https://lyftr-chatbot-frontend-i3xe.onrender.com/" , *, http://localhost:3000/ ',
    )
    get_settings.cache_clear()
    settings = Settings(_env_file=None)

    assert "*" not in settings.allowed_origins_list
    assert settings.allowed_origins_list == [
        DEPLOYED_FRONTEND_ORIGIN,
        "http://localhost:3000",
    ]

    app = create_app()
    with TestClient(app) as client:
        resp = client.options(
            "/chat",
            headers={
                "Origin": DEPLOYED_FRONTEND_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type, accept",
            },
        )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == DEPLOYED_FRONTEND_ORIGIN


def test_health_and_chat_endpoints_include_cors_headers_for_deployed_frontend(
    cors_client, monkeypatch
):
    """GET /health and POST /chat return 200 with exact CORS origin headers."""
    client, _ = cors_client

    async def fake_acompletion(**kwargs):
        return litellm.ModelResponse(
            id="chatcmpl-cors",
            created=1700000000,
            model=kwargs["model"],
            object="chat.completion",
            choices=[
                litellm.Choices(
                    index=0,
                    finish_reason="stop",
                    message=litellm.Message(role="assistant", content="CORS OK"),
                )
            ],
            usage=litellm.Usage(prompt_tokens=8, completion_tokens=2, total_tokens=10),
        )

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    health_resp = client.get("/health", headers={"Origin": DEPLOYED_FRONTEND_ORIGIN})
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"
    assert health_resp.headers.get("access-control-allow-origin") == DEPLOYED_FRONTEND_ORIGIN
    assert health_resp.headers.get("access-control-allow-credentials") == "true"

    chat_resp = client.post(
        "/chat",
        headers={
            "Origin": DEPLOYED_FRONTEND_ORIGIN,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={"session_id": "cors-session-1", "message": "Hello from Render"},
    )
    assert chat_resp.status_code == 200
    assert chat_resp.json()["reply"] == "CORS OK"
    assert chat_resp.headers.get("access-control-allow-origin") == DEPLOYED_FRONTEND_ORIGIN
    assert chat_resp.headers.get("access-control-allow-credentials") == "true"


def test_unhandled_error_preserves_cors_headers(cors_client, monkeypatch):
    """Unexpected server exceptions still emit Access-Control-Allow-Origin headers."""
    client, _ = cors_client

    async def boom(**_kwargs):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr("app.routers.chat.process_chat", boom)

    resp = client.post(
        "/chat",
        headers={
            "Origin": DEPLOYED_FRONTEND_ORIGIN,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={"session_id": "cors-err-1", "message": "Trigger 500"},
    )
    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == DEPLOYED_FRONTEND_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"
