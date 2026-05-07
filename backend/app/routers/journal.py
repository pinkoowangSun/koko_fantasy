import asyncio
from datetime import datetime, date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.journal import JournalEntry
from app.models.user import User
from app.routers.auth import require_approved
from app.schemas.journal import JournalCreate, JournalResponse, JournalUpdate
from app.services.context_service import refresh_profile_summary

router = APIRouter(prefix="/journal", tags=["journal"])


@router.get("/", response_model=List[JournalResponse])
async def list_entries(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    q = select(JournalEntry).where(JournalEntry.user_id == current_user.id)
    if start_date:
        q = q.where(JournalEntry.entry_date >= start_date)
    if end_date:
        q = q.where(JournalEntry.entry_date <= end_date)
    q = q.order_by(JournalEntry.entry_date.desc())
    return (await db.execute(q)).scalars().all()


@router.post("/", response_model=JournalResponse, status_code=201)
async def create_entry(
    body: JournalCreate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    entry = JournalEntry(user_id=current_user.id, **body.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    asyncio.create_task(refresh_profile_summary(current_user.id))
    return entry


@router.get("/{entry_id}", response_model=JournalResponse)
async def get_entry(
    entry_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JournalEntry).where(JournalEntry.id == entry_id, JournalEntry.user_id == current_user.id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Journal entry not found")
    return entry


@router.patch("/{entry_id}", response_model=JournalResponse)
async def update_entry(
    entry_id: int,
    body: JournalUpdate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JournalEntry).where(JournalEntry.id == entry_id, JournalEntry.user_id == current_user.id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Journal entry not found")

    for k, v in body.model_dump(exclude_none=True).items():
        setattr(entry, k, v)
    entry.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(entry)
    asyncio.create_task(refresh_profile_summary(current_user.id))
    return entry


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JournalEntry).where(JournalEntry.id == entry_id, JournalEntry.user_id == current_user.id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Journal entry not found")
    await db.delete(entry)
    await db.commit()
    asyncio.create_task(refresh_profile_summary(current_user.id))
