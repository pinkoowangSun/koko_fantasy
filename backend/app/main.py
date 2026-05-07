from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import auth, bot, briefing, calendar, documents, finance, journal, memory, search, tasks, users, workout
from app.services.reminder_service import start_scheduler, stop_scheduler

FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Koko — Personal Life Manager", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes ────────────────────────────────────────────────────────────────
for r in [auth, tasks, journal, documents, memory, briefing, search, users, calendar, bot, workout, finance]:
    app.include_router(r.router, prefix="/api")


@app.get("/api/config")
async def public_config():
    return {
        "telegram_bot_username": settings.TELEGRAM_BOT_USERNAME,
        "app_name": "Koko",
    }


# ── Serve frontend ────────────────────────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/dashboard")
    async def serve_dashboard():
        return FileResponse(str(FRONTEND_DIR / "pages" / "dashboard.html"))

    @app.get("/tasks")
    async def serve_tasks():
        return FileResponse(str(FRONTEND_DIR / "pages" / "tasks.html"))

    @app.get("/documents")
    async def serve_documents():
        return FileResponse(str(FRONTEND_DIR / "pages" / "documents.html"))

    @app.get("/profile")
    async def serve_profile():
        return FileResponse(str(FRONTEND_DIR / "pages" / "profile.html"))

    @app.get("/workout")
    async def serve_workout():
        return FileResponse(str(FRONTEND_DIR / "pages" / "workout.html"))

    @app.get("/users")
    async def serve_users():
        return FileResponse(str(FRONTEND_DIR / "pages" / "users.html"))

    @app.get("/finance")
    async def serve_finance():
        return FileResponse(str(FRONTEND_DIR / "pages" / "finance.html"))
