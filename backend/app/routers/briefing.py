from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.journal import JournalEntry
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.ai_service import generate_briefing

router = APIRouter(prefix="/briefing", tags=["briefing"])


@router.get("/")
async def get_briefing(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    now = datetime.utcnow()
    next_24h = now + timedelta(hours=24)

    tasks = (await db.execute(
        select(Task)
        .where(Task.user_id == current_user.id, Task.status.in_(["todo", "in_progress"]))
        .order_by(Task.due_date.asc().nullslast())
        .limit(10)
    )).scalars().all()

    entries = (await db.execute(
        select(JournalEntry).where(
            JournalEntry.user_id == current_user.id,
            JournalEntry.entry_date == today,
        )
    )).scalars().all()

    reminders = (await db.execute(
        select(Reminder).where(
            Reminder.user_id == current_user.id,
            Reminder.sent.is_(False),
            Reminder.remind_at <= next_24h,
        ).order_by(Reminder.remind_at)
    )).scalars().all()

    def fmt_tasks():
        if not tasks:
            return "No active tasks."
        lines = [f"  - [{t.priority}] {t.title}" + (f" (due {t.due_date.date()})" if t.due_date else "") for t in tasks]
        return f"{len(tasks)} active task(s):\n" + "\n".join(lines)

    def fmt_journal():
        if not entries:
            return "No entries today."
        return f"{len(entries)} entry(ies): " + "; ".join(
            (e.title or (e.content or "")[:60]) for e in entries
        )

    def fmt_reminders():
        if not reminders:
            return "No reminders in the next 24 hours."
        lines = [f"  - {r.message} at {r.remind_at.strftime('%H:%M UTC')}" for r in reminders[:5]]
        return f"{len(reminders)} reminder(s):\n" + "\n".join(lines)

    briefing_text = await generate_briefing(
        current_user.id, fmt_tasks(), fmt_journal(), fmt_reminders()
    )
    return {
        "briefing": briefing_text,
        "tasks_count": len(tasks),
        "journal_entries_today": len(entries),
        "upcoming_reminders": len(reminders),
        "date": today.isoformat(),
    }
