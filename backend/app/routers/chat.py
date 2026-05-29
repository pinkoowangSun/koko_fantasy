"""Web chat endpoint — JWT-authenticated, same AI pipeline as the Telegram bot."""
import asyncio
from datetime import datetime, timezone as _tz
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.memory import MemoryItem
from app.models.user import User
from app.routers.auth import require_approved
from app.routers.bot import _execute_read, _execute_write
from app.services.ai_service import classify_intent, generate_contextual_response
from app.services.context_service import build_rich_context, refresh_profile_summary
from app.services.intent_registry import ACTION_CONFIGS, DOMAIN_CONFIGS

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessageRequest(BaseModel):
    message: str


@router.post("/message")
async def web_chat_message(
    body: ChatMessageRequest,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    user = current_user
    user_tz = user.timezone or "UTC"

    memory_items = (await db.execute(
        select(MemoryItem).where(MemoryItem.user_id == user.id).limit(20)
    )).scalars().all()

    now_utc = datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    ctx_parts = [
        f"current_time_utc: {now_utc}",
        f"user_timezone: {user_tz}",
    ]
    ctx_parts.extend(f"{m.key}: {m.value}" for m in memory_items)
    if user.profile_summary:
        ctx_parts.append(f"\nUser Profile Summary:\n{user.profile_summary}")
    ctx = "; ".join(ctx_parts)

    phase1 = await classify_intent(user.id, body.message, ctx, user_timezone=user_tz)
    action_cfg = ACTION_CONFIGS.get(phase1.action)

    if not action_cfg:
        return {"response": phase1.response}

    tier = action_cfg.tier

    if tier == "write":
        result = await _execute_write(phase1.action, phase1.domain, phase1.data, user, db)
        if action_cfg.profile_refresh:
            asyncio.create_task(refresh_profile_summary(user.id))
        return {"response": result.get("response") or phase1.response}

    if tier == "read":
        result = await _execute_read(phase1.action, phase1.domain, phase1.data, user, db)
        if result is not None:
            return {"response": result.get("response") or phase1.response}
        domain_cfg = DOMAIN_CONFIGS.get(phase1.domain)
        scope = [domain_cfg.scope_kw] if domain_cfg and domain_cfg.scope_kw else []
        if not scope:
            return {"response": phase1.response}
        rich_ctx = await build_rich_context(user.id, db, scope, user_timezone=user_tz)
        response = await generate_contextual_response(
            user_id=user.id,
            message=body.message,
            profile_summary=user.profile_summary or "",
            rich_context=rich_ctx,
            user_timezone=user_tz,
        )
        return {"response": response}

    if tier == "conversational":
        if not phase1.context_scope:
            return {"response": phase1.response}
        use_tools = "tools" in phase1.context_scope
        data_scope = [s for s in phase1.context_scope if s != "tools"]
        rich_ctx = await build_rich_context(user.id, db, data_scope, user_timezone=user_tz) if data_scope else ""
        response = await generate_contextual_response(
            user_id=user.id,
            message=body.message,
            profile_summary=user.profile_summary or "",
            rich_context=rich_ctx,
            user_timezone=user_tz,
            use_tools=use_tools,
        )
        return {"response": response}

    return {"response": phase1.response}
