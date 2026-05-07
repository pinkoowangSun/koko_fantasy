from datetime import date, datetime, time as time_
from typing import List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.document import Document
from app.models.journal import JournalEntry
from app.models.task import Task
from app.models.user import User
from app.routers.auth import require_approved

router = APIRouter(prefix="/calendar", tags=["calendar"])

PRIORITY_COLOR = {
    "urgent": "#ef4444",
    "high": "#f97316",
    "medium": "#3b82f6",
    "low": "#6b7280",
}

MOOD_EMOJI = {
    "great": "😄",
    "good": "🙂",
    "neutral": "😐",
    "low": "😔",
    "stressed": "😤",
}


def _user_local_date(user: User) -> date:
    try:
        return datetime.now(ZoneInfo(user.timezone or "UTC")).date()
    except (ZoneInfoNotFoundError, Exception):
        return date.today()


def _day_range(d: date):
    """Return (start_datetime, end_datetime) covering the full calendar day."""
    return datetime.combine(d, time_.min), datetime.combine(d, time_(23, 59, 59, 999999))


@router.get("/events")
async def get_events(
    start: date = Query(...),
    end: date = Query(...),
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    start_dt = datetime.combine(start, time_.min)
    end_dt = datetime.combine(end, time_(23, 59, 59, 999999))
    events: List[dict] = []

    tasks = (await db.execute(
        select(Task).where(
            Task.user_id == uid,
            Task.due_date.is_not(None),
            Task.due_date >= start_dt,
            Task.due_date <= end_dt,
        )
    )).scalars().all()
    for t in tasks:
        events.append({
            "id": f"task-{t.id}",
            "title": t.title,
            "start": t.due_date.date().isoformat(),
            "backgroundColor": PRIORITY_COLOR.get(t.priority, "#3b82f6"),
            "borderColor": PRIORITY_COLOR.get(t.priority, "#3b82f6"),
            "extendedProps": {"type": "task", "ref_id": t.id, "status": t.status, "priority": t.priority},
        })

    journal = (await db.execute(
        select(JournalEntry).where(
            JournalEntry.user_id == uid,
            JournalEntry.entry_date >= start,
            JournalEntry.entry_date <= end,
        )
    )).scalars().all()
    for j in journal:
        mood_icon = MOOD_EMOJI.get(j.mood, "") if j.mood else ""
        base_title = j.title or "Journal"
        event_title = f"{mood_icon} {base_title}".strip() if mood_icon else f"📓 {base_title}"
        events.append({
            "id": f"journal-{j.id}",
            "title": event_title,
            "start": j.entry_date.isoformat(),
            "backgroundColor": "#10b981",
            "borderColor": "#10b981",
            "extendedProps": {"type": "journal", "ref_id": j.id, "mood": j.mood},
        })

    docs = (await db.execute(
        select(Document).where(
            Document.user_id == uid,
            Document.created_at >= start_dt,
            Document.created_at <= end_dt,
        )
    )).scalars().all()
    for d in docs:
        events.append({
            "id": f"doc-{d.id}",
            "title": f"📄 {d.original_name}",
            "start": d.created_at.date().isoformat(),
            "backgroundColor": "#f59e0b",
            "borderColor": "#f59e0b",
            "extendedProps": {"type": "document", "ref_id": d.id},
        })

    return events


@router.get("/day-detail")
async def get_day_detail(
    day: date = Query(...),
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    day_start, day_end = _day_range(day)

    tasks = (await db.execute(
        select(Task).where(
            Task.user_id == uid,
            Task.due_date >= day_start,
            Task.due_date <= day_end,
        )
    )).scalars().all()

    journal = (await db.execute(
        select(JournalEntry).where(
            JournalEntry.user_id == uid,
            JournalEntry.entry_date == day,
        )
    )).scalars().all()

    docs = (await db.execute(
        select(Document).where(
            Document.user_id == uid,
            Document.created_at >= day_start,
            Document.created_at <= day_end,
        )
    )).scalars().all()

    return {
        "date": day.isoformat(),
        "tasks": [
            {"id": t.id, "title": t.title, "status": t.status, "priority": t.priority}
            for t in tasks
        ],
        "journal": [
            {
                "id": j.id,
                "title": j.title,
                "content": j.content,
                "content_html": j.content_html,
                "mood": j.mood,
                "mood_icon": MOOD_EMOJI.get(j.mood, "") if j.mood else "",
                "source": j.source,
            }
            for j in journal
        ],
        "documents": [
            {"id": d.id, "original_name": d.original_name, "source": d.source}
            for d in docs
        ],
    }


@router.get("/today")
async def get_today_summary(
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    today = _user_local_date(current_user)
    today_start, today_end = _day_range(today)

    tasks = (await db.execute(
        select(Task).where(
            Task.user_id == uid,
            Task.status.notin_(["done", "cancelled"]),
            or_(
                and_(Task.due_date >= today_start, Task.due_date <= today_end),
                and_(Task.due_date.is_(None), func.date(Task.created_at) == today.isoformat()),
            ),
        ).order_by(Task.created_at.desc())
    )).scalars().all()

    journal = (await db.execute(
        select(JournalEntry).where(
            JournalEntry.user_id == uid,
            JournalEntry.entry_date == today,
        ).order_by(JournalEntry.created_at.desc())
    )).scalars().all()

    return {
        "date": today.isoformat(),
        "tasks": [
            {"id": t.id, "title": t.title, "status": t.status, "priority": t.priority}
            for t in tasks
        ],
        "journal": [
            {
                "id": j.id,
                "title": j.title,
                "mood": j.mood,
                "mood_icon": MOOD_EMOJI.get(j.mood, "") if j.mood else "",
                "source": j.source,
            }
            for j in journal
        ],
    }
