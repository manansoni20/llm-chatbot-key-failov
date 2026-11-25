"""Phase 2 tests for LiteLLM Gemini integration, exact API contract, caching, failover, and persistence."""

import logging

import litellm
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import Base, get_db
from app.main import app

EXPECTED_TOP_LEVEL_KEYS = {"session_id", "reply", "metadata"}
EXPECTED_METADATA_KEYS = {
    "resolution_source",
    "model",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "key_id",
    "fallback_attempts",
}


def _make_model_response(
    text: str,
    prompt_tokens: int = 12,
    completion_tokens: int = 8,
    model: str = "gemini/gemini-2.5-flash",
) -> litellm.ModelResponse:
    """Build a real LiteLLM ModelResponse object."""
    return litellm.ModelResponse(
        id="chatcmpl-test-id",
        created=1700000000,
        model=model,
        object="chat.completion",
        choices=[
            litellm.Choices(
                index=0,
                finish_reason="stop",
                message=litellm.Message(role="assistant", content=text),
            )
        ],
        usage=litellm.Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


@pytest.fixture
def isolated_client(tmp_path, monkeypatch):
    """Provide a FastAPI TestClient backed by an isolated SQLite DB and fresh LiteLLM cache."""
    db_file = tmp_path / "test_chat.db"
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

    monkeypatch.setenv("GEMINI_API_KEYS", "secret-alpha-key,secret-beta-key")
    monkeypatch.setenv("LLM_MODEL", "gemini/gemini-2.5-flash")
    monkeypatch.setenv("SYSTEM_PROMPT", "You are a helpful test assistant.")
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "false")

    get_settings.cache_clear()
    litellm.cache = None
    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    litellm.cache = None
    get_settings.cache_clear()
    test_engine.dispose()


def test_live_inference_exact_contract_and_sqlite_persistence(isolated_client, monkeypatch):
    """POST /chat returns exact {session_id, reply, metadata} contract and persists turns."""
    captured_calls = []

    async def fake_acompletion(**kwargs):
        captured_calls.append(kwargs)
        return _make_model_response("Paris is the capital of France.", 14, 9)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    resp = isolated_client.post(
        "/chat",
        json={"session_id": "sess-live-1", "message": "What is the capital of France?"},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == EXPECTED_TOP_LEVEL_KEYS
    assert set(body["metadata"].keys()) == EXPECTED_METADATA_KEYS
    assert body["session_id"] == "sess-live-1"
    assert body["reply"] == "Paris is the capital of France."

    meta = body["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "gemini/gemini-2.5-flash"
    assert meta["input_tokens"] == 14
    assert meta["output_tokens"] == 9
    assert isinstance(meta["latency_ms"], int) and not isinstance(meta["latency_ms"], bool)
    assert meta["latency_ms"] >= 0
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0
    assert len(captured_calls) == 1
    assert captured_calls[0]["api_key"] == "secret-alpha-key"
    assert captured_calls[0]["api_base"] == "https://generativelanguage.googleapis.com/v1beta"

    history_resp = isolated_client.get("/sessions/sess-live-1/messages")
    assert history_resp.status_code == 200
    messages = history_resp.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is the capital of France?"
    assert messages[0]["metadata"] is None
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Paris is the capital of France."
    assert set(messages[1]["metadata"].keys()) == EXPECTED_METADATA_KEYS
    assert messages[1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert messages[1]["metadata"]["input_tokens"] == 14
    assert messages[1]["metadata"]["output_tokens"] == 9
    assert messages[1]["metadata"]["key_id"] == "key_1"


def test_cache_hit_preserves_exact_contract_and_null_key_id(isolated_client, monkeypatch):
    """Cached responses preserve exact contract with resolution_source=LLM_CACHE and key_id=null."""
    call_count = 0

    async def fake_acompletion(**_kwargs):
        nonlocal call_count
        call_count += 1
        return _make_model_response("Cached answer 42", prompt_tokens=18, completion_tokens=7)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    first = isolated_client.post(
        "/chat",
        json={"session_id": "sess-cache-a", "message": "Meaning of life?"},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert set(first_data.keys()) == EXPECTED_TOP_LEVEL_KEYS
    assert set(first_data["metadata"].keys()) == EXPECTED_METADATA_KEYS
    assert first_data["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert first_data["metadata"]["key_id"] == "key_1"
    assert first_data["metadata"]["fallback_attempts"] == 0
    assert call_count == 1

    # Fresh session with identical message & system prompt hits LiteLLM cache
    second = isolated_client.post(
        "/chat",
        json={"session_id": "sess-cache-b", "message": "Meaning of life?"},
    )
    assert second.status_code == 200
    second_data = second.json()
    assert call_count == 1  # Upstream model was NOT called again
    assert set(second_data.keys()) == EXPECTED_TOP_LEVEL_KEYS
    assert set(second_data["metadata"].keys()) == EXPECTED_METADATA_KEYS
    assert second_data["session_id"] == "sess-cache-b"
    assert second_data["reply"] == first_data["reply"]
    assert second_data["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second_data["metadata"]["model"] == first_data["metadata"]["model"]
    assert second_data["metadata"]["input_tokens"] == 18
    assert second_data["metadata"]["output_tokens"] == 7
    assert second_data["metadata"]["key_id"] is None
    assert second_data["metadata"]["fallback_attempts"] == 0
    assert isinstance(second_data["metadata"]["latency_ms"], int) and not isinstance(
        second_data["metadata"]["latency_ms"], bool
    )
    assert second_data["metadata"]["latency_ms"] >= 0


def test_cache_keys_account_for_history_message_model_and_system_prompt(
    isolated_client, monkeypatch
):
    """Different histories, messages, models, or system prompts must not share cached replies."""
    call_count = 0

    async def fake_acompletion(**kwargs):
        nonlocal call_count
        call_count += 1
        return _make_model_response(
            f"Reply #{call_count}",
            prompt_tokens=10 + call_count,
            completion_tokens=5,
            model=kwargs["model"],
        )

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    # 1. Initial message in sess-iso
    r1 = isolated_client.post(
        "/chat",
        json={"session_id": "sess-iso", "message": "Hello"},
    )
    assert r1.status_code == 200
    assert r1.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert call_count == 1

    # 2. Same user text "Hello" in the SAME session now has prior history -> cache MISS
    r2 = isolated_client.post(
        "/chat",
        json={"session_id": "sess-iso", "message": "Hello"},
    )
    assert r2.status_code == 200
    assert r2.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r2.json()["reply"] == "Reply #2"
    assert call_count == 2

    # 3. Different message in a fresh session -> cache MISS
    r3 = isolated_client.post(
        "/chat",
        json={"session_id": "sess-iso-other", "message": "Goodbye"},
    )
    assert r3.status_code == 200
    assert r3.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert call_count == 3

    # 4. Different model for "Hello" in fresh session -> cache MISS
    r4 = isolated_client.post(
        "/chat",
        json={
            "session_id": "sess-iso-model",
            "message": "Hello",
            "model": "gemini/gemini-2.0-flash",
        },
    )
    assert r4.status_code == 200
    assert r4.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert call_count == 4

    # 5. Different system prompt for "Hello" in fresh session -> cache MISS
    monkeypatch.setenv("SYSTEM_PROMPT", "You are a pirate assistant.")
    get_settings.cache_clear()
    r5 = isolated_client.post(
        "/chat",
        json={"session_id": "sess-iso-sys", "message": "Hello"},
    )
    assert r5.status_code == 200
    assert r5.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert call_count == 5


def test_multi_turn_conversation_history_sent_and_retrieved(isolated_client, monkeypatch):
    """Multi-turn chat sends full system + history + prompt and retrieves chronological messages."""
    recorded_histories = []

    async def fake_acompletion(**kwargs):
        recorded_histories.append(kwargs["messages"])
        turn_num = len(recorded_histories)
        return _make_model_response(f"Assistant turn {turn_num}", 10 * turn_num, 6)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    r1 = isolated_client.post(
        "/chat",
        json={"session_id": "sess-multi", "message": "My name is Ada."},
    )
    assert r1.status_code == 200

    r2 = isolated_client.post(
        "/chat",
        json={"session_id": "sess-multi", "message": "What is my name?"},
    )
    assert r2.status_code == 200

    assert recorded_histories[0] == [
        {"role": "system", "content": "You are a helpful test assistant."},
        {"role": "user", "content": "My name is Ada."},
    ]
    assert recorded_histories[1] == [
        {"role": "system", "content": "You are a helpful test assistant."},
        {"role": "user", "content": "My name is Ada."},
        {"role": "assistant", "content": "Assistant turn 1"},
        {"role": "user", "content": "What is my name?"},
    ]

    history_resp = isolated_client.get("/sessions/sess-multi/messages")
    assert history_resp.status_code == 200
    msgs = history_resp.json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "My name is Ada."),
        ("assistant", "Assistant turn 1"),
        ("user", "What is my name?"),
        ("assistant", "Assistant turn 2"),
    ]
    assert set(msgs[1]["metadata"].keys()) == EXPECTED_METADATA_KEYS
    assert set(msgs[3]["metadata"].keys()) == EXPECTED_METADATA_KEYS


def test_simulated_failure_key1_falls_back_to_key2(isolated_client, monkeypatch):
    """X-Simulate-Failure: key_1=429 triggers fallback to key_2 when enabled."""
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "true")
    get_settings.cache_clear()

    used_keys = []

    async def fake_acompletion(**kwargs):
        used_keys.append(kwargs["api_key"])
        return _make_model_response("Recovered with key_2", 15, 5)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    resp = isolated_client.post(
        "/chat",
        headers={"X-Simulate-Failure": "key_1=429"},
        json={"session_id": "sess-sim-1", "message": "Test failover"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == EXPECTED_TOP_LEVEL_KEYS
    assert data["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1
    assert used_keys == ["secret-beta-key"]


def test_simulated_failure_ignored_when_disabled(isolated_client, monkeypatch):
    """X-Simulate-Failure has no effect when ENABLE_FAILURE_SIMULATION=false."""
    used_keys = []

    async def fake_acompletion(**kwargs):
        used_keys.append(kwargs["api_key"])
        return _make_model_response("Normal key_1 execution", 11, 4)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    resp = isolated_client.post(
        "/chat",
        headers={"X-Simulate-Failure": "*=429"},
        json={"session_id": "sess-sim-off", "message": "Should ignore simulation"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["metadata"]["key_id"] == "key_1"
    assert data["metadata"]["fallback_attempts"] == 0
    assert used_keys == ["secret-alpha-key"]


@pytest.mark.parametrize(
    "header_value",
    [
        "key_1=500,key_2=429",
        "*=429",
    ],
)
def test_simulated_all_keys_fail_returns_503_and_skips_persistence(
    isolated_client, monkeypatch, header_value
):
    """All keys failing returns HTTP 503 with exact detail and stores nothing in SQLite."""
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "true")
    get_settings.cache_clear()

    async def fake_acompletion(**_kwargs):
        raise AssertionError("acompletion should not be reached when all keys are simulated to fail")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    session_id = f"sess-fail-{header_value}"
    resp = isolated_client.post(
        "/chat",
        headers={"X-Simulate-Failure": header_value},
        json={"session_id": session_id, "message": "Fail everywhere"},
    )
    assert resp.status_code == 503
    assert resp.json() == {"detail": "all providers unavailable"}

    history = isolated_client.get(f"/sessions/{session_id}/messages")
    assert history.status_code == 200
    assert history.json()["messages"] == []


def test_provider_429_and_5xx_failover_without_exposing_keys(
    isolated_client, monkeypatch, caplog
):
    """Provider 429/5xx errors trigger key failover and never leak API keys in response or logs."""
    attempts = []

    async def fake_acompletion(**kwargs):
        attempts.append(kwargs["api_key"])
        if kwargs["api_key"] == "secret-alpha-key":
            raise litellm.exceptions.RateLimitError(
                message="429 Resource exhausted for secret-alpha-key",
                llm_provider="gemini",
                model=kwargs["model"],
            )
        return _make_model_response("Success after 429 failover", 20, 10)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    with caplog.at_level(logging.WARNING):
        resp = isolated_client.post(
            "/chat",
            json={"session_id": "sess-real-failover", "message": "Handle 429"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1
    assert attempts == ["secret-alpha-key", "secret-beta-key"]

    serialized_resp = str(data)
    assert "secret-alpha-key" not in serialized_resp
    assert "secret-beta-key" not in serialized_resp
    assert "secret-alpha-key" not in caplog.text
    assert "secret-beta-key" not in caplog.text


def test_all_keys_fail_with_provider_5xx_preserves_prior_history(
    isolated_client, monkeypatch
):
    """When all keys fail with 5xx/429 on turn 2, HTTP 503 is returned and turn 1 remains intact."""
    fail_all = False

    async def fake_acompletion(**kwargs):
        if fail_all:
            raise litellm.exceptions.InternalServerError(
                message="500 Internal Server Error",
                llm_provider="gemini",
                model=kwargs["model"],
            )
        return _make_model_response("Turn 1 worked", 10, 5)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    ok_resp = isolated_client.post(
        "/chat",
        json={"session_id": "sess-preserve", "message": "First question"},
    )
    assert ok_resp.status_code == 200

    fail_all = True
    fail_resp = isolated_client.post(
        "/chat",
        json={"session_id": "sess-preserve", "message": "Second question that fails"},
    )
    assert fail_resp.status_code == 503
    assert fail_resp.json() == {"detail": "all providers unavailable"}

    history = isolated_client.get("/sessions/sess-preserve/messages").json()["messages"]
    assert len(history) == 2
    assert [m["content"] for m in history] == ["First question", "Turn 1 worked"]


@pytest.mark.parametrize(
    "model_name,expected_segment",
    [
        ("gemini/gemini-3.1-flash-lite", "models/gemini-3.1-flash-lite:generateContent"),
        ("gemini/gemini-2.5-flash", "models/gemini-2.5-flash:generateContent"),
        ("gemini/gemini-flash-latest", "models/gemini-flash-latest:generateContent"),
        ("gemini/gemini-3-flash-preview", "models/gemini-3-flash-preview:generateContent"),
    ],
)
def test_gemini_requests_target_v1beta_endpoint_via_real_litellm(
    isolated_client, monkeypatch, model_name, expected_segment
):
    """
    Verify real LiteLLM URL construction targets /v1beta (never /v1alpha),
    preserves x-goog-api-key auth, key failover, and caching.
    """
    import httpx
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

    recorded_requests = []

    async def fake_http_post(self, url, **kwargs):
        headers = kwargs.get("headers") or {}
        api_key = headers.get("x-goog-api-key")
        recorded_requests.append((url, api_key))

        if api_key == "secret-alpha-key":
            return httpx.Response(
                status_code=429,
                json={"error": {"code": 429, "message": "Quota exceeded"}},
                request=httpx.Request("POST", url),
            )

        return httpx.Response(
            status_code=200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": f"v1beta response for {model_name}"}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 9,
                    "candidatesTokenCount": 6,
                    "totalTokenCount": 15,
                },
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setenv("LLM_MODEL", model_name)
    get_settings.cache_clear()
    monkeypatch.setattr(AsyncHTTPHandler, "post", fake_http_post)

    # First call: key_1 gets 429 -> falls back to key_2 -> both target /v1beta
    resp1 = isolated_client.post(
        "/chat",
        json={"session_id": f"sess-v1beta-{model_name}", "message": "Ping v1beta"},
    )
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert body1["reply"] == f"v1beta response for {model_name}"
    assert body1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert body1["metadata"]["key_id"] == "key_2"
    assert body1["metadata"]["fallback_attempts"] == 1
    assert body1["metadata"]["input_tokens"] == 9
    assert body1["metadata"]["output_tokens"] == 6
    assert isinstance(body1["metadata"]["latency_ms"], int)

    assert len(recorded_requests) == 2
    for url, header_key in recorded_requests:
        assert url == f"https://generativelanguage.googleapis.com/v1beta/{expected_segment}"
        assert "/v1alpha/" not in url
        assert "key=" not in url
    assert [k for _, k in recorded_requests] == ["secret-alpha-key", "secret-beta-key"]

    # Second identical call hits LLM_CACHE without making another HTTP POST
    resp2 = isolated_client.post(
        "/chat",
        json={"session_id": f"sess-v1beta-cache-{model_name}", "message": "Ping v1beta"},
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert len(recorded_requests) == 2
    assert body2["metadata"]["resolution_source"] == "LLM_CACHE"
    assert body2["metadata"]["key_id"] is None
    assert body2["metadata"]["fallback_attempts"] == 0
    assert body2["metadata"]["input_tokens"] == 9
    assert body2["metadata"]["output_tokens"] == 6


def test_default_model_is_compatible_with_v1beta_generate_content(isolated_client, monkeypatch):
    """
    Regression test: default LLM_MODEL is gemini/gemini-3.1-flash-lite and routes
    to the v1beta generateContent endpoint via LiteLLM without hitting v1alpha.
    """
    import httpx
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

    from app.config import Settings

    monkeypatch.delenv("LLM_MODEL", raising=False)
    get_settings.cache_clear()

    assert Settings(_env_file=None).llm_model == "gemini/gemini-3.1-flash-lite"

    recorded_urls = []

    async def fake_http_post(self, url, **kwargs):
        recorded_urls.append(url)
        return httpx.Response(
            status_code=200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "Default model OK"}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 7,
                    "candidatesTokenCount": 3,
                    "totalTokenCount": 10,
                },
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(AsyncHTTPHandler, "post", fake_http_post)

    resp = isolated_client.post(
        "/chat",
        json={"session_id": "sess-default-model", "message": "Verify default model"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "Default model OK"
    assert body["metadata"]["model"] == "gemini/gemini-3.1-flash-lite"
    assert body["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert body["metadata"]["key_id"] == "key_1"
    assert recorded_urls == [
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"
    ]

