"""Internal endpoints used exclusively by the Telegram bot, secured with BOT_API_KEY."""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone as _tz
from pathlib import Path
from typing import Optional

import httpx
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
from app.models.workout import WorkoutLog, WorkoutPlan
from app.services.ai_service import (
    classify_intent,
    generate_briefing,
    generate_contextual_response,
    parse_workout_log,
    generate_workout_plan,
)
from app.services.context_service import build_rich_context, refresh_profile_summary
from app.services.intent_registry import ACTION_CONFIGS
from app.services.rag_service import extract_text, index_document, query_and_answer

router = APIRouter(prefix="/bot", tags=["bot"])


# ── Timezone helpers ──────────────────────────────────────────────────────────

def _local_date(user: User) -> date:
    """Return today's date in the user's local timezone (falls back to UTC)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(user.timezone or "UTC")).date()
    except Exception:
        return date.today()


def _fmt_date(dt_utc: datetime, tz_str: Optional[str]) -> str:
    """Format a naive UTC datetime as a local date string (no time component)."""
    try:
        if tz_str and tz_str != "UTC":
            from zoneinfo import ZoneInfo
            return dt_utc.replace(tzinfo=_tz.utc).astimezone(ZoneInfo(tz_str)).strftime("%b %d")
    except Exception:
        pass
    return dt_utc.strftime("%b %d")


# ── Auth + user helpers ───────────────────────────────────────────────────────

def _parse_dt(s: str) -> datetime:
    """Parse any ISO 8601 datetime string → naive UTC datetime for DB."""
    s = s.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(_tz.utc).replace(tzinfo=None)
    return dt


def _fmt_dt(dt_utc: datetime, tz_str: Optional[str]) -> str:
    """Format a naive UTC datetime in the user's local timezone."""
    try:
        if tz_str and tz_str != "UTC":
            from zoneinfo import ZoneInfo
            return dt_utc.replace(tzinfo=_tz.utc).astimezone(ZoneInfo(tz_str)).strftime("%b %d at %I:%M %p %Z")
    except Exception:
        pass
    return dt_utc.strftime("%b %d at %H:%M UTC")


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


# ── Write helpers (shared by orchestrator + direct endpoints) ─────────────────

async def _handle_create_task(data: dict, user: User, db: AsyncSession) -> dict:
    due_date = None
    reminder_at = None

    if data.get("due_date"):
        try:
            due_date = _parse_dt(data["due_date"])
        except ValueError:
            pass

    if data.get("remind_at"):
        try:
            reminder_at = _parse_dt(data["remind_at"])
            if reminder_at <= datetime.utcnow():
                reminder_at = None
        except ValueError:
            pass
    elif due_date:
        if due_date - datetime.utcnow() > timedelta(days=1):
            reminder_at = due_date - timedelta(days=1)
        else:
            reminder_at = due_date

    task = Task(
        user_id=user.id,
        title=data.get("title", "Untitled task"),
        description=data.get("description"),
        priority=data.get("priority", "medium"),
        due_date=due_date,
        reminder_at=reminder_at,
        tags=data.get("tags", []),
    )
    db.add(task)
    await db.flush()

    if reminder_at:
        db.add(Reminder(
            user_id=user.id,
            task_id=task.id,
            message=f"⏰ Reminder: {task.title}",
            remind_at=reminder_at,
        ))

    await db.commit()
    await db.refresh(task)

    fmt = _fmt_dt(reminder_at, user.timezone) if reminder_at else None
    msg = f"✅ Task added: *{task.title}*"
    if fmt:
        msg += f"\n⏰ Reminder set for {fmt}"
    return {"response": msg, "data": {"id": task.id, "title": task.title, "reminder_formatted": fmt}}


async def _handle_complete_task(data: dict, user: User, db: AsyncSession) -> dict:
    title = data.get("title", "")
    result = await db.execute(
        select(Task).where(
            Task.user_id == user.id,
            Task.title.ilike(f"%{title}%"),
            Task.status.in_(["todo", "in_progress"]),
        )
    )
    task = result.scalars().first()
    if not task:
        return {"response": "Couldn't find that task. Use /tasks to see your list.", "data": {}}
    task.status = "done"
    task.updated_at = datetime.utcnow()
    await db.commit()
    return {"response": f"✅ Done: *{task.title}*", "data": {"title": task.title}}


async def _handle_delete_task(data: dict, user: User, db: AsyncSession) -> dict:
    title = data.get("title", "")
    result = await db.execute(
        select(Task).where(
            Task.user_id == user.id,
            Task.title.ilike(f"%{title}%"),
        )
    )
    task = result.scalars().first()
    if not task:
        return {"response": f"No task matching *{title}* found.", "data": {}}
    await db.delete(task)
    await db.commit()
    return {"response": f"🗑 Task deleted: *{task.title}*", "data": {"title": task.title}}


async def _handle_update_task(data: dict, user: User, db: AsyncSession) -> dict:
    title = data.get("title", "")
    result = await db.execute(
        select(Task).where(
            Task.user_id == user.id,
            Task.title.ilike(f"%{title}%"),
            Task.status.in_(["todo", "in_progress"]),
        )
    )
    task = result.scalars().first()
    if not task:
        return {"response": f"No active task matching *{title}* found.", "data": {}}
    if "priority" in data:
        task.priority = data["priority"]
    if "description" in data:
        task.description = data["description"]
    if "status" in data:
        task.status = data["status"]
    if "due_date" in data:
        try:
            task.due_date = _parse_dt(data["due_date"])
        except ValueError:
            pass
    task.updated_at = datetime.utcnow()
    await db.commit()
    return {"response": f"✏️ Task updated: *{task.title}*", "data": {"title": task.title}}


async def _handle_create_journal(data: dict, user: User, db: AsyncSession) -> dict:
    entry_date = _local_date(user)
    if data.get("entry_date"):
        try:
            entry_date = date.fromisoformat(data["entry_date"])
        except ValueError:
            pass
    entry = JournalEntry(
        user_id=user.id,
        content=data.get("content", ""),
        mood=data.get("mood"),
        entry_date=entry_date,
        source="telegram",
    )
    db.add(entry)
    await db.commit()
    mood_str = f" (mood: {entry.mood})" if entry.mood else ""
    return {"response": f"📓 Journal entry saved{mood_str}!", "data": {"entry_date": str(entry_date)}}


async def _handle_delete_journal(data: dict, user: User, db: AsyncSession) -> dict:
    entry_date_str = data.get("entry_date")
    if not entry_date_str:
        return {"response": "Please specify which date's entry to delete.", "data": {}}
    try:
        entry_date = date.fromisoformat(entry_date_str)
    except ValueError:
        return {"response": "Invalid date format. Use YYYY-MM-DD.", "data": {}}

    result = await db.execute(
        select(JournalEntry).where(
            JournalEntry.user_id == user.id,
            JournalEntry.entry_date == entry_date,
        )
    )
    entries = result.scalars().all()
    if not entries:
        return {"response": f"No journal entry found for {entry_date}.", "data": {}}
    for e in entries:
        await db.delete(e)
    await db.commit()
    return {"response": f"🗑 Journal entry for {entry_date} deleted.", "data": {}}


async def _handle_create_workout(data: dict, user: User, db: AsyncSession) -> dict:
    log_date = _local_date(user)
    if data.get("log_date"):
        try:
            log_date = date.fromisoformat(data["log_date"])
        except ValueError:
            pass
    parsed = await parse_workout_log(user.id, data.get("raw_text", ""))
    log = WorkoutLog(
        user_id=user.id,
        log_date=log_date,
        raw_text=data.get("raw_text", ""),
        category=parsed.get("category"),
        summary=parsed.get("summary"),
        source="telegram",
    )
    db.add(log)
    await db.commit()
    cat = (log.category or "workout").replace("_", " ").title()
    msg = f"💪 Workout logged! ({cat})"
    if log.summary:
        msg += f"\n_{log.summary}_"
    return {"response": msg, "data": {"category": log.category, "summary": log.summary}}


async def _handle_delete_workout(data: dict, user: User, db: AsyncSession) -> dict:
    log_date_str = data.get("log_date")
    if not log_date_str:
        return {"response": "Please specify which date's workout to delete.", "data": {}}
    try:
        log_date = date.fromisoformat(log_date_str)
    except ValueError:
        return {"response": "Invalid date format. Use YYYY-MM-DD.", "data": {}}

    result = await db.execute(
        select(WorkoutLog).where(
            WorkoutLog.user_id == user.id,
            WorkoutLog.log_date == log_date,
        )
    )
    logs = result.scalars().all()
    if not logs:
        return {"response": f"No workout found for {log_date}.", "data": {}}
    for l in logs:
        await db.delete(l)
    await db.commit()
    return {"response": f"🗑 Workout session for {log_date} deleted.", "data": {}}


async def _handle_create_memory(data: dict, user: User, db: AsyncSession) -> dict:
    item = MemoryItem(
        user_id=user.id,
        key=data.get("key", "note"),
        value=data.get("value", ""),
        category=data.get("category", "general"),
    )
    db.add(item)
    await db.commit()
    return {"response": "🧠 Got it, I'll remember that!", "data": {}}


async def _handle_delete_memory(data: dict, user: User, db: AsyncSession) -> dict:
    key = data.get("key", "")
    result = await db.execute(
        select(MemoryItem).where(
            MemoryItem.user_id == user.id,
            MemoryItem.key.ilike(f"%{key}%"),
        )
    )
    items = result.scalars().all()
    if not items:
        return {"response": f"No memory found with key *{key}*.", "data": {}}
    for item in items:
        await db.delete(item)
    await db.commit()
    return {"response": f"🗑 Memory *{key}* removed.", "data": {}}


# ── Read helpers ──────────────────────────────────────────────────────────────

async def _handle_list_tasks(user: User, db: AsyncSession) -> dict:
    tasks = (await db.execute(
        select(Task)
        .where(Task.user_id == user.id, Task.status.in_(["todo", "in_progress"]))
        .order_by(Task.due_date.asc().nullslast())
        .limit(15)
    )).scalars().all()

    if not tasks:
        return {"response": "You have no active tasks. 🎉", "data": {"tasks": []}}

    now = datetime.utcnow()
    lines = [f"📋 *Your tasks ({len(tasks)}):*"]
    for t in tasks:
        due_str = ""
        if t.due_date:
            if t.due_date < now:
                due_str = f" ⚠ overdue ({_fmt_date(t.due_date, user.timezone)})"
            else:
                due_str = f" — due {_fmt_date(t.due_date, user.timezone)}"
        pri = {"urgent": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(t.priority, "")
        lines.append(f"{pri} {t.title}{due_str}")
    return {"response": "\n".join(lines), "data": {"tasks": [{"id": t.id, "title": t.title} for t in tasks]}}


async def _handle_read_journal(data: dict, user: User, db: AsyncSession) -> dict:
    entry_date = None
    if data.get("entry_date"):
        try:
            entry_date = date.fromisoformat(data["entry_date"])
        except ValueError:
            pass

    query = select(JournalEntry).where(JournalEntry.user_id == user.id)
    if entry_date:
        query = query.where(JournalEntry.entry_date == entry_date)
    query = query.order_by(JournalEntry.entry_date.desc()).limit(1)

    entry = (await db.execute(query)).scalar_one_or_none()
    if not entry:
        return {"response": "No journal entry found.", "data": {}}

    mood_str = f" | Mood: {entry.mood}" if entry.mood else ""
    text = f"📓 *{entry.entry_date}{mood_str}*\n\n{entry.content or '(no content)'}"
    return {"response": text, "data": {}}


async def _handle_read_workout_plan(user: User, db: AsyncSession) -> dict:
    today = _local_date(user)
    ws = today - timedelta(days=today.weekday())
    day_name = today.strftime("%A").lower()

    plan_row = (await db.execute(
        select(WorkoutPlan).where(
            WorkoutPlan.user_id == user.id,
            WorkoutPlan.week_start == ws,
        )
    )).scalar_one_or_none()

    if not plan_row:
        return {"response": "No workout plan for this week yet. Use /genplan to create one!", "data": {}}

    day_plan = plan_row.plan.get(day_name)
    if not day_plan:
        return {"response": "No plan found for today.", "data": {}}

    focus = day_plan.get("focus", "Workout")
    exercises = day_plan.get("exercises") or []
    duration = day_plan.get("duration_min", 0)
    warmup = day_plan.get("warmup", "")
    notes = day_plan.get("notes", "")

    if not exercises or "rest" in focus.lower():
        msg = f"🛋 Today is a rest day — *{focus}*"
        if notes:
            msg += f"\n💡 {notes}"
    else:
        lines = [f"🏋 Today's workout — *{focus}*"]
        if warmup:
            lines.append(f"🔥 Warm-up: {warmup}")
        for ex in exercises:
            sets = ex.get("sets", "")
            reps = ex.get("reps", "")
            weight = ex.get("weight", "")
            detail = f"{sets}×{reps}" if sets and reps else reps or sets
            weight_str = " (bodyweight)" if weight == "bodyweight" else (f" @ {weight}" if weight else "")
            lines.append(f"  • {ex.get('name', '')}: {detail}{weight_str}")
        if duration:
            lines.append(f"⏱ ~{duration} min")
        if notes:
            lines.append(f"📝 {notes}")
        msg = "\n".join(lines)

    return {"response": msg, "data": {}}


async def _handle_generate_workout_plan(user: User, db: AsyncSession) -> dict:
    today_local = _local_date(user)
    four_weeks_ago = today_local - timedelta(weeks=4)
    logs = (await db.execute(
        select(WorkoutLog)
        .where(WorkoutLog.user_id == user.id, WorkoutLog.log_date >= four_weeks_ago)
        .order_by(WorkoutLog.log_date.asc())
    )).scalars().all()

    logs_context = "\n".join(
        f"[{l.log_date}] {l.category or 'unknown'}: {l.raw_text}" for l in logs
    ) if logs else ""

    memory_items = (await db.execute(
        select(MemoryItem).where(MemoryItem.user_id == user.id).limit(20)
    )).scalars().all()

    workout_pref = next((m.value for m in memory_items if m.key.strip().lower() == "workout"), "")
    user_memory = "; ".join(f"{m.key}: {m.value}" for m in memory_items if m.key.strip().lower() != "workout")

    result = await generate_workout_plan(user.id, logs_context, user_memory, workout_pref)

    ws = today_local - timedelta(days=today_local.weekday())
    existing = (await db.execute(
        select(WorkoutPlan).where(WorkoutPlan.user_id == user.id, WorkoutPlan.week_start == ws)
    )).scalar_one_or_none()

    if existing:
        existing.plan = result.get("plan", {})
        existing.ai_notes = result.get("notes")
        existing.generated_at = datetime.utcnow()
    else:
        db.add(WorkoutPlan(
            user_id=user.id,
            week_start=ws,
            plan=result.get("plan", {}),
            ai_notes=result.get("notes"),
        ))
    await db.commit()

    notes = result.get("notes", "")
    msg = "💪 Your weekly workout plan is ready! Open the app to see the full schedule."
    if notes:
        msg += f"\n\n📋 _{notes}_"
    return {"response": msg, "data": {"notes": notes}}


async def _handle_generate_briefing(user: User, db: AsyncSession) -> dict:
    today = _local_date(user)
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
    return {"response": briefing, "data": {}}


async def _handle_query_document(data: dict, user: User) -> dict:
    question = data.get("question", data.get("query", ""))
    answer = await query_and_answer(user.id, question)
    return {"response": answer, "data": {}}


# ── Orchestrator dispatch ─────────────────────────────────────────────────────

async def _execute_write(action: str, domain: str, data: dict, user: User, db: AsyncSession) -> dict:
    try:
        if domain == "task":
            if action == "create":
                return await _handle_create_task(data, user, db)
            elif action == "complete":
                return await _handle_complete_task(data, user, db)
            elif action == "delete":
                return await _handle_delete_task(data, user, db)
            elif action == "update":
                return await _handle_update_task(data, user, db)
        elif domain == "journal":
            if action == "create":
                return await _handle_create_journal(data, user, db)
            elif action == "delete":
                return await _handle_delete_journal(data, user, db)
        elif domain == "workout":
            if action == "create":
                return await _handle_create_workout(data, user, db)
            elif action == "delete":
                return await _handle_delete_workout(data, user, db)
        elif domain == "memory":
            if action == "create":
                return await _handle_create_memory(data, user, db)
            elif action == "delete":
                return await _handle_delete_memory(data, user, db)
    except Exception as exc:
        print(f"[bot] execute_write failed {action}+{domain}: {exc}")

    return {"response": "Something went wrong. Please try again.", "data": {}}


async def _execute_read(action: str, domain: str, data: dict, user: User, db: AsyncSession) -> dict:
    try:
        if domain == "task" and action == "list":
            return await _handle_list_tasks(user, db)
        elif domain == "journal" and action == "read":
            return await _handle_read_journal(data, user, db)
        elif domain == "workout":
            if action == "read":
                return await _handle_read_workout_plan(user, db)
            elif action == "generate":
                return await _handle_generate_workout_plan(user, db)
        elif domain == "briefing" and action == "generate":
            return await _handle_generate_briefing(user, db)
        elif domain == "document":
            if action == "query":
                return await _handle_query_document(data, user)
            elif action == "search":
                return await _handle_query_document(data, user)
    except Exception as exc:
        print(f"[bot] execute_read failed {action}+{domain}: {exc}")

    return {"response": "Something went wrong. Please try again.", "data": {}}


# ── Main intent endpoint ──────────────────────────────────────────────────────

class IntentRequest(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    message: str


@router.post("/intent", dependencies=[Depends(_bot_auth)])
async def bot_intent(body: IntentRequest, db: AsyncSession = Depends(get_db)):
    user = await _get_or_create_user(body.telegram_id, body.username, db)

    # Build Phase 1 context
    memory_items = (await db.execute(
        select(MemoryItem).where(MemoryItem.user_id == user.id).limit(20)
    )).scalars().all()

    now_utc = datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    ctx_parts = [
        f"current_time_utc: {now_utc}",
        f"user_timezone: {user.timezone or 'UTC'}",
    ]
    ctx_parts.extend(f"{m.key}: {m.value}" for m in memory_items)
    if user.profile_summary:
        ctx_parts.append(f"\nUser Profile Summary:\n{user.profile_summary}")
    ctx = "; ".join(ctx_parts)

    # Phase 1 — classify
    phase1 = await classify_intent(user.id, body.message, ctx)
    action_cfg = ACTION_CONFIGS.get(phase1.action)

    if not action_cfg:
        return {"action": "chat", "domain": "", "response": phase1.response, "data": {}}

    tier = action_cfg.tier

    # WRITE
    if tier == "write":
        result = await _execute_write(phase1.action, phase1.domain, phase1.data, user, db)
        if action_cfg.profile_refresh:
            asyncio.create_task(refresh_profile_summary(user.id))
        return {"action": phase1.action, "domain": phase1.domain, **result}

    # READ
    if tier == "read":
        result = await _execute_read(phase1.action, phase1.domain, phase1.data, user, db)
        return {"action": phase1.action, "domain": phase1.domain, **result}

    # CONVERSATIONAL
    if tier == "conversational":
        if not phase1.context_scope:
            return {"action": "chat", "domain": "", "response": phase1.response, "data": {}}

        rich_ctx = await build_rich_context(user.id, db, phase1.context_scope)
        response = await generate_contextual_response(
            user_id=user.id,
            message=body.message,
            profile_summary=user.profile_summary or "",
            rich_context=rich_ctx,
        )
        return {"action": "chat", "domain": "", "response": response, "data": {}}

    # MEDIA (handled by /media/{domain}, shouldn't arrive via text)
    return {"action": phase1.action, "domain": phase1.domain, "response": phase1.response, "data": {}}


# ── Direct endpoints (used by command handlers + web, unchanged contracts) ─────

class BotTaskCreate(BaseModel):
    telegram_id: int
    title: str
    description: Optional[str] = None
    priority: str = "medium"
    due_date: Optional[str] = None
    remind_at: Optional[str] = None
    tags: list[str] = []


@router.post("/tasks", dependencies=[Depends(_bot_auth)])
async def bot_create_task(body: BotTaskCreate, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    result = await _handle_create_task(body.model_dump(exclude={"telegram_id"}), user, db)
    asyncio.create_task(refresh_profile_summary(user.id))
    return result["data"] | {"response": result["response"]}


@router.get("/tasks", dependencies=[Depends(_bot_auth)])
async def bot_list_tasks(telegram_id: int, db: AsyncSession = Depends(get_db)):
    user = await _require_user(telegram_id, db)
    result = await _handle_list_tasks(user, db)
    return result


class BotCompleteTask(BaseModel):
    telegram_id: int
    title: str


@router.post("/tasks/complete", dependencies=[Depends(_bot_auth)])
async def bot_complete_task(body: BotCompleteTask, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    result = await _handle_complete_task({"title": body.title}, user, db)
    asyncio.create_task(refresh_profile_summary(user.id))
    return result["data"] | {"ok": "title" in result["data"]}


class BotDeleteTask(BaseModel):
    telegram_id: int
    title: str


@router.delete("/tasks", dependencies=[Depends(_bot_auth)])
async def bot_delete_task(body: BotDeleteTask, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    result = await _handle_delete_task({"title": body.title}, user, db)
    asyncio.create_task(refresh_profile_summary(user.id))
    return result


# ── Journal endpoints ─────────────────────────────────────────────────────────

class BotJournalCreate(BaseModel):
    telegram_id: int
    content: str
    mood: Optional[str] = None
    entry_date: Optional[str] = None


@router.post("/journal", dependencies=[Depends(_bot_auth)])
async def bot_create_journal(body: BotJournalCreate, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    result = await _handle_create_journal(body.model_dump(exclude={"telegram_id"}), user, db)
    asyncio.create_task(refresh_profile_summary(user.id))
    return {"ok": True}


class BotDeleteJournal(BaseModel):
    telegram_id: int
    entry_date: str


@router.delete("/journal", dependencies=[Depends(_bot_auth)])
async def bot_delete_journal(body: BotDeleteJournal, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    result = await _handle_delete_journal({"entry_date": body.entry_date}, user, db)
    asyncio.create_task(refresh_profile_summary(user.id))
    return result


# ── Briefing ──────────────────────────────────────────────────────────────────

@router.get("/briefing", dependencies=[Depends(_bot_auth)])
async def bot_briefing(telegram_id: int, db: AsyncSession = Depends(get_db)):
    user = await _require_user(telegram_id, db)
    result = await _handle_generate_briefing(user, db)
    return {"briefing": result["response"]}


# ── Document Q&A ──────────────────────────────────────────────────────────────

class BotDocQA(BaseModel):
    telegram_id: int
    question: str


@router.post("/doc-qa", dependencies=[Depends(_bot_auth)])
async def bot_doc_qa(body: BotDocQA, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    result = await _handle_query_document({"question": body.question}, user)
    return {"answer": result["response"]}


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
    result = await _handle_create_memory(
        {"key": body.key, "value": body.value, "category": body.category}, user, db
    )
    asyncio.create_task(refresh_profile_summary(user.id))
    return {"ok": True}


class BotDeleteMemory(BaseModel):
    telegram_id: int
    key: str


@router.delete("/memory", dependencies=[Depends(_bot_auth)])
async def bot_delete_memory(body: BotDeleteMemory, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    result = await _handle_delete_memory({"key": body.key}, user, db)
    asyncio.create_task(refresh_profile_summary(user.id))
    return result


# ── Workout ───────────────────────────────────────────────────────────────────

def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


class BotWorkoutLog(BaseModel):
    telegram_id: int
    raw_text: str
    log_date: Optional[str] = None


@router.post("/workout/log", dependencies=[Depends(_bot_auth)])
async def bot_log_workout(body: BotWorkoutLog, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    result = await _handle_create_workout(
        {"raw_text": body.raw_text, "log_date": body.log_date}, user, db
    )
    asyncio.create_task(refresh_profile_summary(user.id))
    return result["data"] | {"ok": True}


class BotDeleteWorkout(BaseModel):
    telegram_id: int
    log_date: str


@router.delete("/workout/log", dependencies=[Depends(_bot_auth)])
async def bot_delete_workout(body: BotDeleteWorkout, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    result = await _handle_delete_workout({"log_date": body.log_date}, user, db)
    asyncio.create_task(refresh_profile_summary(user.id))
    return result


@router.get("/workout/today", dependencies=[Depends(_bot_auth)])
async def bot_workout_today(telegram_id: int, db: AsyncSession = Depends(get_db)):
    user = await _require_user(telegram_id, db)
    result = await _handle_read_workout_plan(user, db)
    return {"message": result["response"]}


class BotGeneratePlan(BaseModel):
    telegram_id: int


@router.post("/workout/plan/generate", dependencies=[Depends(_bot_auth)])
async def bot_generate_plan(body: BotGeneratePlan, db: AsyncSession = Depends(get_db)):
    user = await _require_user(body.telegram_id, db)
    result = await _handle_generate_workout_plan(user, db)
    return {"ok": True, "notes": result["data"].get("notes", "")}


# ── Media (stub — expanded per domain as features are added) ──────────────────

@router.post("/media/{domain}", dependencies=[Depends(_bot_auth)])
async def bot_media(
    domain: str,
    telegram_id: int = Form(...),
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Entry point for photo/file messages requiring a vision LLM.
    Each domain (nutrition, etc.) will be handled here as features are added.
    """
    user = await _require_user(telegram_id, db)
    # Placeholder — returns a graceful fallback until the domain is implemented
    return {
        "action": "upload",
        "domain": domain,
        "response": (
            f"I can see you sent a {domain} image! "
            "This feature is coming soon — for now, feel free to describe it in text."
        ),
        "data": {},
    }


# ── User approval ─────────────────────────────────────────────────────────────

async def _send_telegram_message(chat_id: int, text: str):
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        )


@router.post("/users/{user_id}/approve", dependencies=[Depends(_bot_auth)])
async def bot_approve_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    user.status = "approved"
    user.updated_at = datetime.utcnow()
    await db.commit()
    try:
        await _send_telegram_message(user.telegram_id, "You can now access Koko Fantasy! Welcome babe:)")
    except Exception:
        pass
    return {"ok": True}


@router.post("/users/{user_id}/reject", dependencies=[Depends(_bot_auth)])
async def bot_reject_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    user.status = "rejected"
    user.updated_at = datetime.utcnow()
    await db.commit()
    try:
        await _send_telegram_message(user.telegram_id, "Sorry, your access request to Koko Fantasy has been declined.")
    except Exception:
        pass
    return {"ok": True}
