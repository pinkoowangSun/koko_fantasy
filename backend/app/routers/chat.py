from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.memory import MemoryItem
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.ai_service import chat

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    source: str = "web"


@router.post("/")
async def send_message(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    memory_items = (await db.execute(
        select(MemoryItem).where(MemoryItem.user_id == current_user.id).limit(20)
    )).scalars().all()

    context_parts = [f"{m.key}: {m.value}" for m in memory_items]
    if current_user.preferences:
        context_parts.insert(0, f"Preferences: {current_user.preferences}")

    reply = await chat(
        current_user.id,
        body.message,
        "; ".join(context_parts),
        body.source,
    )
    return {"reply": reply}
