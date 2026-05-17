from datetime import date, datetime, time as time_
from typing import List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from collections import defaultdict

from app.database import get_db
from app.models.document import Document
from app.models.finance import Transaction
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
            or_(
                and_(Task.due_date.is_not(None), Task.due_date >= start_dt, Task.due_date <= end_dt),
                and_(Task.due_date.is_(None), Task.created_at >= start_dt, Task.created_at <= end_dt),
            ),
        )
    )).scalars().all()
    for t in tasks:
        events.append({
            "id": f"task-{t.id}",
            "title": t.title,
            "start": (t.due_date.date() if t.due_date else t.created_at.date()).isoformat(),
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

    # Finance: one net-per-currency event per day
    fin_txs = (await db.execute(
        select(Transaction).where(
            Transaction.user_id == uid,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
    )).scalars().all()

    # Group by (date, currency) → net
    fin_by_day: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in fin_txs:
        sign = 1 if t.transaction_type == "income" else -1
        fin_by_day[t.transaction_date][t.currency] += sign * t.amount

    for day_date, by_currency in fin_by_day.items():
        parts = []
        for cur, net in sorted(by_currency.items()):
            parts.append(f"{'+'if net>=0 else ''}{net:,.0f} {cur}")
        label = " · ".join(parts)
        color = "#10b981" if all(v >= 0 for v in by_currency.values()) else "#ef4444"
        events.append({
            "id": f"finance-{day_date.isoformat()}",
            "title": f"💰 {label}",
            "start": day_date.isoformat(),
            "backgroundColor": color,
            "borderColor": color,
            "extendedProps": {"type": "finance"},
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
            or_(
                and_(Task.due_date >= day_start, Task.due_date <= day_end),
                and_(Task.due_date.is_(None), func.date(Task.created_at) == day.isoformat()),
            ),
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

    finance_txs = (await db.execute(
        select(Transaction).where(
            Transaction.user_id == uid,
            Transaction.transaction_date == day,
        ).order_by(Transaction.created_at.desc())
    )).scalars().all()

    fin_income: dict[str, float] = defaultdict(float)
    fin_expense: dict[str, float] = defaultdict(float)
    for t in finance_txs:
        if t.transaction_type == "income":
            fin_income[t.currency] += t.amount
        elif t.transaction_type == "expense":
            fin_expense[t.currency] += t.amount

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
        "finance": {
            "income_by_currency": {k: round(v, 2) for k, v in fin_income.items()},
            "expense_by_currency": {k: round(v, 2) for k, v in fin_expense.items()},
            "transactions": [
                {"id": t.id, "amount": t.amount, "transaction_type": t.transaction_type,
                 "category": t.category, "currency": t.currency, "description": t.description}
                for t in finance_txs
            ],
        },
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

    finance_txs = (await db.execute(
        select(Transaction).where(
            Transaction.user_id == uid,
            Transaction.transaction_date == today,
        ).order_by(Transaction.created_at.desc())
    )).scalars().all()

    fin_income: dict[str, float] = defaultdict(float)
    fin_expense: dict[str, float] = defaultdict(float)
    for t in finance_txs:
        if t.transaction_type == "income":
            fin_income[t.currency] += t.amount
        elif t.transaction_type == "expense":
            fin_expense[t.currency] += t.amount

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
        "finance": {
            "income_by_currency": {k: round(v, 2) for k, v in fin_income.items()},
            "expense_by_currency": {k: round(v, 2) for k, v in fin_expense.items()},
            "transactions": [
                {"id": t.id, "amount": t.amount, "transaction_type": t.transaction_type,
                 "category": t.category, "currency": t.currency, "description": t.description}
                for t in finance_txs
            ],
        },
    }
