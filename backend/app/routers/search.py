from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.document import Document
from app.models.journal import JournalEntry
from app.models.memory import MemoryItem
from app.models.task import Task
from app.models.user import User
from app.routers.auth import get_current_user

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/")
async def search(
    q: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    term = f"%{q}%"

    tasks = (await db.execute(
        select(Task).where(Task.user_id == uid).where(
            or_(Task.title.ilike(term), Task.description.ilike(term))
        ).limit(10)
    )).scalars().all()

    journal = (await db.execute(
        select(JournalEntry).where(JournalEntry.user_id == uid).where(
            or_(JournalEntry.title.ilike(term), JournalEntry.content.ilike(term))
        ).limit(10)
    )).scalars().all()

    documents = (await db.execute(
        select(Document).where(Document.user_id == uid).where(
            or_(Document.original_name.ilike(term), Document.description.ilike(term))
        ).limit(10)
    )).scalars().all()

    memory = (await db.execute(
        select(MemoryItem).where(MemoryItem.user_id == uid).where(
            or_(MemoryItem.key.ilike(term), MemoryItem.value.ilike(term))
        ).limit(10)
    )).scalars().all()

    return {
        "tasks": [{"id": t.id, "title": t.title, "status": t.status, "priority": t.priority} for t in tasks],
        "journal": [{"id": j.id, "title": j.title, "entry_date": j.entry_date.isoformat()} for j in journal],
        "documents": [{"id": d.id, "name": d.original_name, "indexed": d.indexed} for d in documents],
        "memory": [{"id": m.id, "key": m.key, "value": m.value[:120], "category": m.category} for m in memory],
    }
