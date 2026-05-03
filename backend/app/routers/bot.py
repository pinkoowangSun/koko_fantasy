"""Internal endpoints used exclusively by the Telegram bot, secured with BOT_API_KEY."""
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.document import Document
from app.models.journal import JournalEntry
from app.models.memory import MemoryItem
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User
from app.services.ai_service import detect_intent, generate_briefing
from app.services.rag_service import extract_text, index_document, query_and_answer

router = APIRouter(prefix="/bot", tags=["bot"])


async def _bot_auth(x_bot_key: str = Header(...)):
    if x_bot_key != settings.BOT_API_KEY:
        raise HTTPException(403, "Forbidden")


async def _get_or_create_user(telegram_id: int, username: Optional[str], db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(telegram_id=telegram_id, username=username)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def _require_user(telegram_id: int, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not registered. Send /start first.")
    return user


# ── Intent detection ──────────────────────────────────────────────────────────

class IntentRequest(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    message: str


@router.post("/intent", dependencies=[Depends(_bot_auth)])
async def bot_intent(body: IntentRequest, db: AsyncSession = Depends(get_db)):
    user = await _get_or_create_user(body.telegram_id, body.username, db)

    memory_items = (await db.execute(
        select(MemoryItem).where(MemoryItem.user_id == user.id).limit(20)
    )).scalars().all()
    ctx = "; ".join(f"{m.key}: {m.value}" for m in memory_items)

    return await detect_intent(user.id, body.message, ctx)


# ── Tasks ─────────────────────────────────────────────────────────────────────

class BotTaskCreate(BaseModel):
    telegram_id: int
    title: str
    description: Optional[str] = None
    priority: str = "medium"
    due_date: Optional[str] = None  # ISO string
    tags: list[str] = []


@router.post("/tasks", dependencies=[Depends(_bot_auth)])
async def bot_create_task(body: BotTaskCreate, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)

    due_date = None
    reminder_at = None
    if body.due_date:
        try:
            due_date = datetime.fromisoformat(body.due_date)
            reminder_at = due_date - timedelta(days=1)
        except ValueError:
            pass

    task = Task(
        user_id=user.id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        due_date=due_date,
        reminder_at=reminder_at,
        tags=body.tags,
    )
    db.add(task)
    await db.flush()

    if reminder_at:
        db.add(Reminder(
            user_id=user.id,
            task_id=task.id,
            message=f"Task due: {task.title}",
            remind_at=reminder_at,
        ))

    await db.commit()
    await db.refresh(task)
    return {"id": task.id, "title": task.title, "status": task.status}


@router.get("/tasks", dependencies=[Depends(_bot_auth)])
async def bot_list_tasks(telegram_id: int, db: AsyncSession = Depends(get_db)):
    user = await _require_user(telegram_id, db)
    tasks = (await db.execute(
        select(Task)
        .where(Task.user_id == user.id, Task.status.in_(["todo", "in_progress"]))
        .order_by(Task.due_date.asc().nullslast())
        .limit(15)
    )).scalars().all()
    return {
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "priority": t.priority,
                "status": t.status,
                "due_date": t.due_date.isoformat() if t.due_date else None,
            }
            for t in tasks
        ]
    }


class BotCompleteTask(BaseModel):
    telegram_id: int
    title: str


@router.post("/tasks/complete", dependencies=[Depends(_bot_auth)])
async def bot_complete_task(body: BotCompleteTask, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    result = await db.execute(
        select(Task).where(
            Task.user_id == user.id,
            Task.title.ilike(f"%{body.title}%"),
            Task.status.in_(["todo", "in_progress"]),
        )
    )
    task = result.scalars().first()
    if not task:
        return {"ok": False, "message": "Task not found"}
    task.status = "done"
    task.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "title": task.title}


# ── Journal ───────────────────────────────────────────────────────────────────

class BotJournalCreate(BaseModel):
    telegram_id: int
    content: str
    mood: Optional[str] = None
    entry_date: Optional[str] = None  # ISO date


@router.post("/journal", dependencies=[Depends(_bot_auth)])
async def bot_create_journal(body: BotJournalCreate, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)

    entry_date = date.today()
    if body.entry_date:
        try:
            entry_date = date.fromisoformat(body.entry_date)
        except ValueError:
            pass

    entry = JournalEntry(
        user_id=user.id,
        content=body.content,
        mood=body.mood,
        entry_date=entry_date,
        source="telegram",
    )
    db.add(entry)
    await db.commit()
    return {"ok": True}


# ── Briefing ──────────────────────────────────────────────────────────────────

@router.get("/briefing", dependencies=[Depends(_bot_auth)])
async def bot_briefing(telegram_id: int, db: AsyncSession = Depends(get_db)):
    user = await _require_user(telegram_id, db)
    today = date.today()
    now = datetime.utcnow()

    tasks = (await db.execute(
        select(Task)
        .where(Task.user_id == user.id, Task.status.in_(["todo", "in_progress"]))
        .order_by(Task.due_date.asc().nullslast())
        .limit(10)
    )).scalars().all()

    entries = (await db.execute(
        select(JournalEntry).where(JournalEntry.user_id == user.id, JournalEntry.entry_date == today)
    )).scalars().all()

    reminders = (await db.execute(
        select(Reminder).where(
            Reminder.user_id == user.id,
            Reminder.sent.is_(False),
            Reminder.remind_at <= now + timedelta(hours=24),
        )
    )).scalars().all()

    tasks_txt = (
        f"{len(tasks)} task(s):\n" + "\n".join(f"  - [{t.priority}] {t.title}" for t in tasks)
        if tasks else "No active tasks."
    )
    journal_txt = f"{len(entries)} entry(ies) today." if entries else "No journal entries today."
    reminders_txt = f"{len(reminders)} reminder(s) in next 24h." if reminders else "No upcoming reminders."

    briefing = await generate_briefing(user.id, tasks_txt, journal_txt, reminders_txt)
    return {"briefing": briefing}


# ── Document Q&A ──────────────────────────────────────────────────────────────

class BotDocQA(BaseModel):
    telegram_id: int
    question: str


@router.post("/doc-qa", dependencies=[Depends(_bot_auth)])
async def bot_doc_qa(body: BotDocQA, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    answer = await query_and_answer(user.id, body.question)
    return {"answer": answer}


# ── Document upload ───────────────────────────────────────────────────────────

@router.post("/upload-doc", dependencies=[Depends(_bot_auth)])
async def bot_upload_doc(
    telegram_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_user(telegram_id, db)

    user_dir = settings.DOCUMENTS_DIR / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "file").suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = user_dir / stored_name

    content = await file.read()
    file_path.write_bytes(content)

    doc = Document(
        user_id=user.id,
        stored_name=stored_name,
        original_name=file.filename or stored_name,
        file_path=str(file_path),
        file_size=len(content),
        mime_type=file.content_type,
        source="telegram",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    try:
        text = extract_text(str(file_path), file.content_type)
        if text.strip():
            await index_document(user.id, doc.id, text, {"doc_id": doc.id, "original_name": doc.original_name})
            doc.indexed = True
            await db.commit()
    except Exception as exc:
        print(f"[bot] indexing failed for doc {doc.id}: {exc}")

    return {"id": doc.id, "original_name": doc.original_name, "indexed": doc.indexed}


# ── Memory ────────────────────────────────────────────────────────────────────

class BotMemoryCreate(BaseModel):
    telegram_id: int
    key: str
    value: str
    category: str = "general"


@router.post("/memory", dependencies=[Depends(_bot_auth)])
async def bot_add_memory(body: BotMemoryCreate, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    item = MemoryItem(user_id=user.id, key=body.key, value=body.value, category=body.category)
    db.add(item)
    await db.commit()
    return {"ok": True}
