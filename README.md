# Lyftr AI Full-Stack LLM Chatbot

A full-stack LLM chatbot built with React + Vite, FastAPI, SQLite, LiteLLM (`gemini/gemini-3.1-flash-lite`), and Docker Compose. It provides automatic multi-key failover, response caching, failure simulation via `X-Simulate-Failure`, per-turn token and latency telemetry, and persistent multi-turn conversation history.

---

## Live URLs

> **Status:** Not yet publicly deployed. The placeholders below will be populated once deployed.

- **Frontend (Production URL):** `<PENDING_FRONTEND_DEPLOYMENT_URL>`
- **Backend API (Production URL):** `<PENDING_BACKEND_DEPLOYMENT_URL>`
- **Backend Health Check:** `<PENDING_BACKEND_DEPLOYMENT_URL>/health`
- **Local Development URLs:**
  - Frontend: `http://localhost:3000` (Docker) / `http://localhost:5173` (Vite dev server)
  - Backend: `http://localhost:8000`

---

## Architecture Overview

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
                                │  • v1beta Gemini Route   │                         │  • messages table         │
                                │  • Local Cache (TTL)     │                         │  • Named Docker volume    │
                                │  • Key Pool Failover     │                         └───────────────────────────┘
                                │  • X-Simulate-Failure    │
                                └──────────────────────────┘
```

### Tech Stack

- **Frontend:** React 19, Vite 6, Nginx 1.27 Alpine (multi-stage container on port `3000`)
- **Backend:** Python 3.12+, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2.x (port `8000`)
- **LLM Gateway:** LiteLLM (`gemini/gemini-3.1-flash-lite` over Google AI Studio `v1beta`)
- **Database:** SQLite (`messages` table with `id`, `session_id`, `role`, `content`, `metadata`, `created_at`)
- **Packaging & Tooling:** Docker, Docker Compose, Makefile, Pytest

---

## Run locally: with Docker and without

### Option A: Run with Docker Compose

1. Navigate to the project root and copy the environment template:
   ```bash
   cd llm-chatbot
   cp .env.example .env
   ```
2. Edit `.env` and set `LLM_API_KEYS` to at least **two distinct** Google AI Studio Gemini API keys:
   ```env
   LLM_API_KEYS=your-gemini-key-1,your-gemini-key-2
   ```
3. Build and start both containers:
   ```bash
   make up
   ```
4. Open the application:
   - **Frontend:** http://localhost:3000
   - **Backend:** http://localhost:8000
   - **Health Check:** http://localhost:8000/health
5. Stop the containers while preserving SQLite history in the `sqlite_data` volume (`/data`):
   ```bash
   make down
   ```

### Option B: Run Locally Without Docker

**1. Backend (`http://localhost:8000`):**
```bash
cd llm-chatbot/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="sqlite:///./data/chatbot.db"
export LLM_API_KEYS="your-gemini-key-1,your-gemini-key-2"
export LLM_MODEL="gemini/gemini-3.1-flash-lite"
export ALLOWED_ORIGINS="http://localhost:3000,http://localhost:5173"
export CACHE_ENABLED="true"
export ENABLE_FAILURE_SIMULATION="false"

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**2. Frontend (`http://localhost:5173`):**
```bash
cd llm-chatbot/frontend
npm install
export VITE_API_BASE_URL="http://localhost:8000"
npm run dev
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:////data/chatbot.db` | SQLAlchemy SQLite connection string (use `sqlite:///./data/chatbot.db` outside Docker) |
| `LLM_API_KEYS` | *(empty — required)* | Comma-separated pool of at least 2 distinct Gemini API keys (`key_1`, `key_2`, ...) |
| `LLM_MODEL` | `gemini/gemini-3.1-flash-lite` | LiteLLM Gemini model identifier verified for `v1beta` `generateContent` |
| `GEMINI_API_BASE` | `https://generativelanguage.googleapis.com/v1beta` | Google AI Studio `v1beta` base URL passed to LiteLLM |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated allowed CORS origins |
| `CACHE_ENABLED` | `true` | Enables LiteLLM in-memory response caching |
| `CACHE_TTL_SECONDS` | `3600` | Cache entry time-to-live in seconds |
| `ENABLE_FAILURE_SIMULATION` | `false` | Enables `X-Simulate-Failure` header parsing when set to `true` |
| `SYSTEM_PROMPT` | `You are a helpful, concise, and accurate AI assistant.` | System prompt prepended to every conversation |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend base URL injected into the Vite frontend build |

---

## Design decisions: key fallback, caching, SQLite session storage

### 1. Key Fallback & `v1beta` Routing (`backend/app/services/llm_service.py`)
- **Internal Key Identification:** Configured keys are deduplicated in priority order and mapped internally to `key_1`, `key_2`, etc. Raw API keys are never returned in API responses or emitted in application logs (`litellm.suppress_debug_info = True`).
- **Readiness Enforcement:** `GET /health` verifies live SQLite connectivity (`SELECT 1`) and requires at least two distinct keys (`keys_configured >= 2`), returning HTTP `503` if the database or key pool is unready.
- **Retryable Failover:** On HTTP `429`, quota/`RESOURCE_EXHAUSTED` errors, `5xx` responses, timeouts, or connection errors (as well as `X-Simulate-Failure` rules when `ENABLE_FAILURE_SIMULATION=true`), the gateway increments `fallback_attempts` and automatically retries with the next key in the pool.
- **Outage Semantics:** If every configured key fails, `POST /chat` returns HTTP `503` (`{"detail": "all providers unavailable"}`).
- **Explicit `v1beta` Base URL:** LiteLLM routes newer/alias Gemini models to `/v1alpha` by default. Setting `api_base="https://generativelanguage.googleapis.com/v1beta"` for Google AI Studio (`gemini/*`) models routes requests reliably to `/v1beta/models/{model}:generateContent` with `x-goog-api-key` header auth.

### 2. Response Caching (`LLM_CACHE` vs `LIVE_INFERENCE`)
- **LiteLLM `Cache`:** Initialized with `LiteLLMCacheType.LOCAL`, configurable `ttl`, and `max_messages=None` so multi-turn conversations longer than LiteLLM's default 4-message limit remain cacheable.
- **Cache-Key Scope:** Cache lookup occurs **before** iterating through the API key pool, keying on the `model` and the complete ordered `messages` list (system prompt + conversation history + current user message). Different conversation histories, models, or system prompts never falsely share cached replies.
- **Deterministic Cache Hit Metadata:** Cache hits return immediately with `resolution_source: "LLM_CACHE"`, `key_id: null`, `fallback_attempts: 0`, identical reply text, stored `input_tokens` and `output_tokens`, and integer `latency_ms`.

### 3. SQLite Session Storage (`backend/app/models.py`, `backend/app/services/chat_service.py`)
- **Schema:** The `messages` table stores `id`, `session_id` (indexed), `role`, `content`, `metadata` (JSON column storing all 7 telemetry fields for assistant turns), and `created_at` (with a composite index on `(session_id, created_at)`).
- **WAL & Volume Persistence:** SQLite runs in `WAL` mode locally and persists to `/data/chatbot.db` inside Docker via the named `sqlite_data` volume so conversation history survives container restarts.
- **Transactional Failure Safety:** User and assistant turns are persisted in a single transaction **only after** a successful LLM or cache response—failed `503` requests are never written to conversation history.

---

## Verification: how to see failover, cache hits and per-message token usage

### 1. Health & Readiness Check (`GET /health`)
```bash
curl http://localhost:8000/health
```
Expected ready response (`200 OK`):
```json
{
  "status": "ok",
  "keys_configured": 2,
  "cache_enabled": true
}
```

### 2. Live Inference & Per-Message Token Usage (`LIVE_INFERENCE`)
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "verify-live-1", "message": "Reply with one word: Pong"}'
```
Observed response (`200 OK`):
```json
{
  "session_id": "verify-live-1",
  "reply": "Ping",
  "metadata": {
    "resolution_source": "LIVE_INFERENCE",
    "model": "gemini/gemini-3.1-flash-lite",
    "latency_ms": 3953,
    "input_tokens": 19,
    "output_tokens": 1,
    "key_id": "key_1",
    "fallback_attempts": 0
  }
}
```

### 3. Cache Hit Verification (`LLM_CACHE`)
Send the exact same single-turn message in a fresh session (matching model, system prompt, and message list):
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "verify-cache-2", "message": "Reply with one word: Pong"}'
```
Observed response (`200 OK` — `key_id` is `null`, `fallback_attempts` is `0`, `reply` and token counts match):
```json
{
  "session_id": "verify-cache-2",
  "reply": "Ping",
  "metadata": {
    "resolution_source": "LLM_CACHE",
    "model": "gemini/gemini-3.1-flash-lite",
    "latency_ms": 0,
    "input_tokens": 19,
    "output_tokens": 1,
    "key_id": null,
    "fallback_attempts": 0
  }
}
```

### 4. Simulated Key Failover (`X-Simulate-Failure`)
Ensure `ENABLE_FAILURE_SIMULATION=true` in `.env`, then send a new/uncached prompt with `X-Simulate-Failure: key_1=429`:
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id": "verify-live-1", "message": "Now reply with one word: Ready"}'
```
Observed response (`200 OK` — `key_1` fails with simulated `429`, automatically falls back to `key_2`, `fallback_attempts: 1`, and multi-turn `input_tokens` increases with history):
```json
{
  "session_id": "verify-live-1",
  "reply": "Set",
  "metadata": {
    "resolution_source": "LIVE_INFERENCE",
    "model": "gemini/gemini-3.1-flash-lite",
    "latency_ms": 3873,
    "input_tokens": 29,
    "output_tokens": 1,
    "key_id": "key_2",
    "fallback_attempts": 1
  }
}
```

To verify total outage behavior (`key_1=500,key_2=429` or `*=429`):
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: *=429" \
  -d '{"session_id": "verify-live-1", "message": "Should fail"}'
```
Returns HTTP `503` with `{"detail": "all providers unavailable"}` and leaves `GET /sessions/verify-live-1/messages` unchanged.

### 5. Chronological Session History (`GET /sessions/{session_id}/messages`)
```bash
curl http://localhost:8000/sessions/verify-live-1/messages
```
Returns all stored turns for `verify-live-1` ordered chronologically with full assistant `metadata`. In the React UI (`http://localhost:3000`), every assistant card also surfaces `resolution_source` (color-coded `LIVE_INFERENCE` vs `LLM_CACHE` badge), `model`, `latency_ms`, `input_tokens`, `output_tokens`, `key_id`, and `fallback_attempts` with the required `data-testid` attributes.

### 6. Automated Backend Tests & Frontend Build
```bash
# Backend test suite (22 tests)
cd llm-chatbot/backend
.venv/bin/pytest -v

# Frontend production build
cd ../frontend
npm install
npm run build
```

---

## Setup Used: your editor and AI tools

- **Editor / AI Coding Environment:** Antigravity (AI-assisted development, debugging, and verification)
- **Container Runtime Tooling:** Docker Desktop (Docker & Docker Compose configuration)
- **Version Control & Hosting:** Git and GitHub

---

## Bonus features (if any): what you added beyond the requirements

1. **In-UI Gateway Readiness Card:** The sidebar queries `GET /health` on load (with a manual refresh button) to display live database/key-pool readiness (`status`, `keys_configured`, `cache_enabled`) and surface `503` readiness errors cleanly.
2. **Multi-Session Sidebar Switching:** Users can create multiple fresh sessions in the same browser tab (`New Session`) and switch back to earlier sessions to reload persisted turns and assistant telemetry from SQLite via `GET /sessions/{session_id}/messages`.
3. **Interactive Starter Prompts & Session ID Copy:** The empty-chat view offers quick starter prompts for immediate single-turn/multi-turn/cache testing along with a one-click `Copy ID` button in the chat header.
4. **Responsive Mobile Drawer & Telemetry Grid:** Responsive layout (`@media (max-width: 768px)`) with a collapsible sidebar drawer and an auto-fitting telemetry grid for all seven response metadata fields.
5. **Nginx Reverse-Proxy Fallback:** `frontend/nginx.conf` proxies `/health`, `/chat`, and `/sessions/` to `backend:8000` inside Docker when `VITE_API_BASE_URL` is left empty, while also supporting direct `VITE_API_BASE_URL` calls via CORS.
