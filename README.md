# Koko — Personal Life Manager

AI-powered personal assistant with a Telegram bot client and a web UI. All data stored locally on your VPS.

## Features

- **AI Chat** via DeepSeek — natural language intent detection
- **Task Manager** — create, update, complete, prioritise with due dates & reminders
- **Daily Journal** — plain text via Telegram, rich text via Web UI
- **Document Storage & Q&A** — upload PDFs/DOCX/TXT, ask questions via RAG
- **Memory** — persistent user facts passed as AI context
- **Daily Briefing** — AI-generated summary of tasks, journal, reminders
- **Search** — across tasks, journal, documents, memory
- **Calendar Dashboard** — visual tracker with task/journal/doc overlays
- **Multi-user** — each user sees only their own data; login via Telegram OAuth

---

## Quick Start (bare metal)

### 1. Clone & configure

```bash
cd /root/koko_fantasy
cp .env.example .env
# Edit .env — fill in DEEPSEEK_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_USERNAME,
#             JWT_SECRET, BOT_API_KEY
nano .env
```

### 2. Install backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Install Telegram bot

```bash
cd ../telegram_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Run backend

```bash
cd /root/koko_fantasy/backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The web UI is served at `http://<your-vps-ip>:8000`.

### 5. Run Telegram bot (separate terminal)

```bash
cd /root/koko_fantasy/telegram_bot
source .venv/bin/activate
python -m telegram_bot.bot
```

---

## Docker Compose

```bash
cd /root/koko_fantasy
cp .env.example .env && nano .env
docker compose up -d
```

---

## Telegram Login Widget (Web UI)

The login page uses Telegram's official OAuth widget. Requirements:

1. In [@BotFather](https://t.me/botfather), run `/setdomain` and set your VPS domain (needs HTTPS).
2. Set `TELEGRAM_BOT_USERNAME` in `.env` (without `@`).
3. For HTTPS, use nginx + certbot in front of port 8000.

**nginx config snippet:**
```nginx
server {
    server_name your.domain.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | Default: `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | Default: `deepseek-chat` |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_BOT_USERNAME` | Bot username (no @), for login widget |
| `JWT_SECRET` | Long random string for signing JWTs |
| `BOT_API_KEY` | Shared secret between bot and backend |
| `BOT_API_BASE` | Backend URL as seen by the bot (default: `http://localhost:8000`) |
| `APP_HOST` | Default: `0.0.0.0` |
| `APP_PORT` | Default: `8000` |

---

## Project Structure

```
koko_fantasy/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, mounts all routers
│   │   ├── config.py        # Settings from .env
│   │   ├── database.py      # SQLAlchemy async + SQLite
│   │   ├── models/          # ORM models (User, Task, Journal, …)
│   │   ├── schemas/         # Pydantic request/response schemas
│   │   ├── routers/         # API route handlers
│   │   └── services/        # AI, RAG, reminder scheduler
│   └── requirements.txt
├── telegram_bot/
│   ├── bot.py               # Entry point, registers handlers
│   ├── config.py
│   └── handlers/            # start, chat, tasks, journal, briefing, documents
├── frontend/
│   ├── index.html           # Login page (Telegram OAuth)
│   └── pages/
│       ├── dashboard.html   # Calendar / daily tracker
│       ├── tasks.html       # Task management
│       ├── documents.html   # Document storage + Q&A
│       └── profile.html     # User profile + memory
├── data/                    # Local data (gitignored)
│   ├── db/koko.db           # SQLite
│   ├── documents/           # Uploaded files
│   └── vectors/             # ChromaDB embeddings
└── .env                     # Secrets (never commit)
```

---

## Telegram Bot Commands

| Command | Description |
|---|---|
| `/start` | Intro & registration |
| `/briefing` | AI daily briefing |
| `/tasks` | List active tasks |
| `/done <title>` | Mark task complete |
| `/journal <text>` | Write journal entry |
| `/search <query>` | Search everything |
| Send a file | Upload document (PDF/DOCX/TXT/MD) |
| Free text | AI intent detection (add task, ask doc question, chat…) |

---

## Extending

The architecture is designed for extension:

- **Calendar integration**: Add a `/calendar` router + Google Calendar OAuth
- **Email digest**: Extend `reminder_service.py` with SMTP/SendGrid
- **Voice notes**: Add audio handler in `telegram_bot/handlers/`
- **Webhooks**: Replace polling with `app.run_webhook()` in `bot.py`
- **Auth**: JWT expiry/refresh already wired in `routers/auth.py`
