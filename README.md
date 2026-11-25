# Lyftr AI Full-Stack LLM Chatbot

A production-ready full-stack LLM chatbot featuring a React + Vite frontend, a FastAPI + SQLAlchemy backend, LiteLLM gateway routing for Gemini models, automatic multi-key failover, response caching, failure simulation, SQLite persistence, and multi-stage Docker Compose packaging.

---

## 1. Architecture Overview

```text
┌─────────────────────────┐         HTTP / JSON          ┌──────────────────────────────┐
│  React + Vite Frontend  │ ───────────────────────────► │   FastAPI Backend (:8000)    │
│  (Nginx :3000)          │ ◄─────────────────────────── │                              │
└─────────────────────────┘   {session_id, reply, meta}  │  • GET  /health              │
                                                         │  • POST /chat                │
                                                         │  • GET  /sessions/{id}/msgs  │
                                                         └──────────────┬───────────────┘
                                                                        │
                                             ┌──────────────────────────┴──────────────────────────┐
                                             ▼                                                     ▼
                                ┌──────────────────────────┐                         ┌───────────────────────────┐
                                │   LiteLLM Gateway        │                         │   SQLite (/data/chatbot.db)│
                                │  • Local Cache (TTL)     │                         │  • messages table         │
                                │  • Key Pool Failover     │                         │  • Named Docker volume    │
                                │  • X-Simulate-Failure    │                         └───────────────────────────┘
                                └──────────────────────────┘
```

### Key Design Decisions
- **Cache-First Execution:** LiteLLM checks its in-memory response cache (`model` + complete `messages` array including system prompt and full conversation history) before touching the API key pool. Cache hits return `resolution_source: "LLM_CACHE"`, `key_id: null`, `fallback_attempts: 0`, and stored token counts.
- **Deterministic Key-Pool Failover:** Configured keys are mapped internally to `key_1`, `key_2`, etc. On HTTP `429`, quota errors, `5xx`, timeouts, or simulated failures (`X-Simulate-Failure` when `ENABLE_FAILURE_SIMULATION=true`), the gateway automatically falls back to the next key and records `fallback_attempts`.
- **Clean Failure Semantics:** When all configured keys fail, `POST /chat` returns HTTP `503` (`{"detail": "all providers unavailable"}`) and does **not** persist failed turns to SQLite.

---

## 2. Tech Stack

- **Frontend:** React 19, Vite 6, Nginx (Alpine multi-stage container on port `3000`)
- **Backend:** Python 3.12+, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2.x (on port `8000`)
- **LLM Gateway:** LiteLLM (`gemini/gemini-2.5-flash`, local `Cache`, multi-key failover)
- **Database:** SQLite (persisted via Docker named volume `sqlite_data` mounted at `/data`)
- **Containerization & Tooling:** Docker, Docker Compose, Makefile, Pytest

---

## 3. Setup & Running (Docker & Local)

### Option A: Run with Docker Compose (Recommended)

1. Navigate to the project directory and create your `.env` file:
   ```bash
   cd llm-chatbot
   cp .env.example .env
   ```
2. Edit `.env` and configure at least **two distinct** Gemini API keys in `LLM_API_KEYS`.
3. Build and start both services:
   ```bash
   make up
   ```
4. Access the application:
   - **Frontend UI:** http://localhost:3000
   - **Backend API:** http://localhost:8000
   - **Health Check:** http://localhost:8000/health
5. Stop containers (SQLite data in the `sqlite_data` volume persists across restarts):
   ```bash
   make down
   ```

### Option B: Run Locally Without Docker

**Backend (`localhost:8000`):**
```bash
cd llm-chatbot/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="sqlite:///./data/chatbot.db"
export LLM_API_KEYS="your-gemini-key-1,your-gemini-key-2"
export ALLOWED_ORIGINS="http://localhost:3000,http://localhost:5173"
export ENABLE_FAILURE_SIMULATION="false"

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend (`localhost:5173` or `npm run build`):**
```bash
cd llm-chatbot/frontend
npm install
export VITE_API_BASE_URL="http://localhost:8000"
npm run dev
```

---

## 4. Environment Variables

Defined in [`.env.example`](.env.example):

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:////data/chatbot.db` | SQLAlchemy SQLite connection string (`/data` volume in Docker) |
| `LLM_API_KEYS` | *(empty — required)* | Comma-separated pool of at least 2 distinct Gemini API keys (`key_1`, `key_2`, ...) |
| `LLM_MODEL` | `gemini/gemini-2.5-flash` | LiteLLM Gemini model identifier |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated CORS origins |
| `CACHE_ENABLED` | `true` | Enables LiteLLM response caching |
| `CACHE_TTL_SECONDS` | `3600` | Cache entry time-to-live in seconds |
| `ENABLE_FAILURE_SIMULATION` | `false` | Enables `X-Simulate-Failure` header handling when `true` |
| `SYSTEM_PROMPT` | `You are a helpful, concise, and accurate AI assistant.` | System prompt prepended to every conversation |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend base URL injected into the Vite frontend build |

---

## 5. API Reference & Examples

### `GET /health`
Checks actual SQLite connectivity (`SELECT 1`) and verifies at least 2 distinct API keys are configured.

**Ready (`200 OK`):**
```bash
curl http://localhost:8000/health
```
```json
{
  "status": "ok",
  "keys_configured": 2,
  "cache_enabled": true
}
```

**Unready (`503 Service Unavailable` when DB is unreachable or `< 2` distinct keys configured):**
```json
{
  "status": "unavailable",
  "keys_configured": 1,
  "cache_enabled": true,
  "detail": "at least 2 distinct API keys must be configured"
}
```

---

### `POST /chat`
Sends a user message for a `session_id`, appends conversation history from SQLite, checks LiteLLM cache, and falls back across API keys on `429`/quota/`5xx` errors.

**Request:**
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "demo-session", "message": "What does LiteLLM do?"}'
```

**Live Inference Response (`200 OK`):**
```json
{
  "session_id": "demo-session",
  "reply": "LiteLLM provides a unified interface across LLM providers with caching and fallback.",
  "metadata": {
    "resolution_source": "LIVE_INFERENCE",
    "model": "gemini/gemini-2.5-flash",
    "latency_ms": 342,
    "input_tokens": 16,
    "output_tokens": 14,
    "key_id": "key_1",
    "fallback_attempts": 0
  }
}
```

**Cache Hit Response (`200 OK`):**
```json
{
  "session_id": "demo-session-2",
  "reply": "LiteLLM provides a unified interface across LLM providers with caching and fallback.",
  "metadata": {
    "resolution_source": "LLM_CACHE",
    "model": "gemini/gemini-2.5-flash",
    "latency_ms": 1,
    "input_tokens": 16,
    "output_tokens": 14,
    "key_id": null,
    "fallback_attempts": 0
  }
}
```

**Simulated Failover (`ENABLE_FAILURE_SIMULATION=true`):**
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id": "demo-session", "message": "Explain fallback."}'
```
Returns `key_id: "key_2"` and `fallback_attempts: 1`.

**All Keys Failed (`503 Service Unavailable`, not persisted):**
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: *=429" \
  -d '{"session_id": "demo-session", "message": "Test outage"}'
```
```json
{
  "detail": "all providers unavailable"
}
```

---

### `GET /sessions/{session_id}/messages`
Returns chronologically ordered messages for `session_id` with stored assistant metadata.

```bash
curl http://localhost:8000/sessions/demo-session/messages
```
```json
{
  "session_id": "demo-session",
  "messages": [
    {
      "id": 1,
      "session_id": "demo-session",
      "role": "user",
      "content": "What does LiteLLM do?",
      "metadata": null,
      "created_at": "2026-11-25T03:08:25.375738"
    },
    {
      "id": 2,
      "session_id": "demo-session",
      "role": "assistant",
      "content": "LiteLLM provides a unified interface across LLM providers with caching and fallback.",
      "metadata": {
        "resolution_source": "LIVE_INFERENCE",
        "model": "gemini/gemini-2.5-flash",
        "latency_ms": 342,
        "input_tokens": 16,
        "output_tokens": 14,
        "key_id": "key_1",
        "fallback_attempts": 0
      },
      "created_at": "2026-11-25T03:08:25.375738"
    }
  ]
}
```

---

## 6. Testing & Verification

### Backend Automated Tests
```bash
cd llm-chatbot/backend
.venv/bin/pytest -v
```
Covers:
- `/health` readiness checks (SQLite `SELECT 1`, minimum 2 distinct API keys, duplicate key rejection, CORS headers)
- Exact `POST /chat` JSON contract (`session_id`, `reply`, 7-field `metadata` with integer `latency_ms`)
- LiteLLM response caching (`LLM_CACHE`, `key_id: null`, `fallback_attempts: 0`, cache key isolation across model/system prompt/history)
- Multi-turn conversation history persistence and chronological retrieval
- `X-Simulate-Failure` (`key_1=429`, `key_1=500,key_2=429`, `*=429`) and `ENABLE_FAILURE_SIMULATION=false` guard
- Provider 429/5xx failover without key leakage and HTTP `503` non-persistence

### Frontend Production Build
```bash
cd llm-chatbot/frontend
npm install
npm run build
```
