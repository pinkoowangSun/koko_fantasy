from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.document import Document
from app.models.journal import JournalEntry
from app.models.task import Task
from app.models.user import User
from app.routers.auth import get_current_user

router = APIRouter(prefix="/calendar", tags=["calendar"])

PRIORITY_COLOR = {
    "urgent": "#ef4444",
    "high": "#f97316",
    "medium": "#3b82f6",
    "low": "#6b7280",
}


@router.get("/events")
async def get_events(
    start: date = Query(...),
    end: date = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    events: List[dict] = []

    # Tasks with due_date in range
    tasks = (await db.execute(
        select(Task).where(
            Task.user_id == uid,
            Task.due_date.is_not(None),
            Task.due_date >= str(start),
            Task.due_date <= str(end) + " 23:59:59",
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

    # Journal entries in range
    journal = (await db.execute(
        select(JournalEntry).where(
            JournalEntry.user_id == uid,
            JournalEntry.entry_date >= start,
            JournalEntry.entry_date <= end,
        )
    )).scalars().all()
    for j in journal:
        events.append({
            "id": f"journal-{j.id}",
            "title": j.title or "📓 Journal",
            "start": j.entry_date.isoformat(),
            "backgroundColor": "#10b981",
            "borderColor": "#10b981",
            "extendedProps": {"type": "journal", "ref_id": j.id},
        })

    # Documents uploaded in range
    docs = (await db.execute(
        select(Document).where(
            Document.user_id == uid,
            Document.created_at >= str(start),
            Document.created_at <= str(end) + " 23:59:59",
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    day_str = day.isoformat()

    tasks = (await db.execute(
        select(Task).where(
            Task.user_id == uid,
            Task.due_date >= day_str,
            Task.due_date <= day_str + " 23:59:59",
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
            Document.created_at >= day_str,
            Document.created_at <= day_str + " 23:59:59",
        )
    )).scalars().all()

    return {
        "date": day_str,
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
                "source": j.source,
            }
            for j in journal
        ],
        "documents": [
            {"id": d.id, "original_name": d.original_name, "source": d.source}
            for d in docs
        ],
    }
