from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.memory import MemoryItem
from app.models.user import User
from app.routers.auth import require_approved
from app.schemas.memory import MemoryCreate, MemoryResponse, MemoryUpdate

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/", response_model=List[MemoryResponse])
async def list_memory(
    category: Optional[str] = None,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    q = select(MemoryItem).where(MemoryItem.user_id == current_user.id)
    if category:
        q = q.where(MemoryItem.category == category)
    return (await db.execute(q.order_by(MemoryItem.updated_at.desc()))).scalars().all()


@router.post("/", response_model=MemoryResponse, status_code=201)
async def create_memory(
    body: MemoryCreate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    item = MemoryItem(user_id=current_user.id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=MemoryResponse)
async def update_memory(
    item_id: int,
    body: MemoryUpdate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MemoryItem).where(MemoryItem.id == item_id, MemoryItem.user_id == current_user.id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Memory item not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(item, k, v)
    item.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=204)
async def delete_memory(
    item_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MemoryItem).where(MemoryItem.id == item_id, MemoryItem.user_id == current_user.id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Memory item not found")
    await db.delete(item)
    await db.commit()
