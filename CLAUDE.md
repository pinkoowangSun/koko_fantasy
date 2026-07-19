# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**Koko** is an AI-powered personal life management assistant. It has four runtime components that communicate with each other:
- **Backend** (`/backend`) — FastAPI + SQLAlchemy async + SQLite; serves both the REST API and the frontend static files
- **Scheduler** (`backend/app/scheduler.py`) — standalone APScheduler process for reminders and proactive Telegram notifications
- **Telegram Bot** (`/telegram_bot`) — polls Telegram, interprets commands and free-text via AI, calls the backend
- **Frontend** (`/frontend`) — vanilla HTML + Alpine.js + Tailwind; served from `/frontend/pages/` by the backend at routes like `/dashboard`, `/tasks`, etc.

## Running Locally

### Backend
```bash
cd backend
pip install -r requirements.txt
cd ..                          # run from repo root so relative paths work
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Scheduler (separate terminal)
```bash
cd backend
python -m app.scheduler
```

### Telegram Bot (separate terminal)
```bash
cd telegram_bot
pip install -r requirements.txt
python bot.py
```

### Docker Compose (both services)
```bash
cp .env.example .env   # fill in secrets
docker compose up -d
```

Frontend is served by the backend at `http://localhost:8000`.

## Required Environment Variables

See `.env.example`. The critical ones:

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` | AI calls (OpenAI-compatible) |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_BOT_USERNAME` | For login widget (no `@`) |
| `JWT_SECRET` | Signing JWTs |
| `BOT_API_KEY` | Shared secret between bot ↔ backend |
| `ASSET_ENCRYPTION_KEY` | Fernet key for asset balance amounts at rest |
| `SUPER_ADMIN_TELEGRAM_ID` | Receives user approval requests |

Generate a Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## Architecture

### Request Flow
**Telegram free-text:** User message → `telegram_bot/handlers/chat.py` → `POST /api/bot/message` → `routers/bot.py` → `services/ai_service.py` (DeepSeek intent classification) → dispatches to the relevant router

**Frontend requests:** Alpine.js fetch → `Authorization: Bearer <JWT>` → FastAPI router → SQLAlchemy async session

### AI Intent Classification (`services/ai_service.py`)
DeepSeek returns structured JSON:
```json
{ "action": "create|list|update|delete|...", "domain": "task|journal|finance|...", "data": {...}, "response": "..." }
```
Invalid responses are retried once, then fall back to a "chat" default. `services/intent_registry.py` is the single source of truth for valid actions and domains — update it when adding features.

### User Isolation
Every ORM model has a `user_id` FK. All queries must filter by `current_user.id`. The `require_approved()` FastAPI dependency enforces that only approved users (status=`"approved"`) can access endpoints.

### Authentication Flow
1. Telegram OAuth widget on `/` → `POST /api/auth/login` → backend validates signature → JWT
2. JWT stored in `localStorage` as `auth_token`; sent as `Authorization: Bearer` on all requests
3. New users start as `status="pending"`; super admin approves via Telegram inline button

### Finance Encryption
Asset balance amounts are encrypted with Fernet (`ASSET_ENCRYPTION_KEY`) before
being stored in SQLite. Transaction amounts and finance-goal amounts remain
ordinary SQLite numeric fields so they can be filtered and aggregated.

### Reminders
APScheduler runs as the standalone `app.scheduler` process. It checks every
minute for due reminders and local-time workout/check-in notifications, then
sends them through the Telegram Bot API. Do not run more than one scheduler
replica.

## Key Directories

| Path | Contents |
|---|---|
| `backend/app/models/` | SQLAlchemy ORM models (DB schema) |
| `backend/app/routers/` | FastAPI endpoint controllers (one file per domain) |
| `backend/app/schemas/` | Pydantic DTOs for request/response validation |
| `backend/app/services/` | AI, RAG (ChromaDB), reminders, context aggregation, JWT |
| `telegram_bot/handlers/` | One handler file per domain + `api.py` (HTTP client to backend) |
| `frontend/pages/` | One HTML page per feature area |
| `data/db/` | `koko.db` SQLite file (gitignored) |
| `data/vectors/` | ChromaDB embeddings (gitignored) |

## Tests

Run the regression tests from the repository root:

```bash
PYTHONPATH=backend:. python -m unittest discover -s tests
```

## Adding a New Feature Domain

1. Add ORM model in `backend/app/models/`
2. Add Pydantic schemas in `backend/app/schemas/`
3. Add router in `backend/app/routers/` and register it in `backend/app/main.py`
4. Add the domain/actions to `backend/app/services/intent_registry.py`
5. Add a handler file in `telegram_bot/handlers/` and register it in `telegram_bot/bot.py`
6. Add a page in `frontend/pages/` and a nav link in the shared header
