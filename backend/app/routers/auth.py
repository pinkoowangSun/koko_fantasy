import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()
log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify_telegram_data(data: dict) -> bool:
    check_hash = data.get("hash")
    if not check_hash:
        return False
    filtered = {k: v for k, v in data.items() if k != "hash"}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(filtered.items()))
    secret = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode()).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if int(data.get("auth_date", 0)) < time.time() - 86400:
        return False
    return hmac.compare_digest(check_hash, expected)


def create_jwt(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(days=settings.JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_jwt(credentials.credentials)
        user_id: int = payload["user_id"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_approved(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency that blocks pending/rejected users from accessing features."""
    if current_user.status != "approved":
        raise HTTPException(status_code=403, detail="pending_approval")
    return current_user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


async def _notify_admin(user: User):
    """Send an inline-button approval request to the super admin."""
    try:
        username_str = f"@{user.username}" if user.username else f"ID {user.telegram_id}"
        text = (
            f"👤 *New access request*\n"
            f"User: {username_str}\n"
            f"Telegram ID: `{user.telegram_id}`\n"
            f"Registered: {user.created_at.strftime('%Y-%m-%d %H:%M')} UTC"
        )
        reply_markup = {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve:{user.id}"},
                {"text": "❌ Reject",  "callback_data": f"reject:{user.id}"},
            ]]
        }
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": settings.SUPER_ADMIN_TELEGRAM_ID,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": reply_markup,
                },
            )
    except Exception as e:
        log.error("[auth] failed to notify admin: %s", e)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/telegram")
async def telegram_login(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    if not _verify_telegram_data(dict(data)):
        raise HTTPException(status_code=401, detail="Invalid Telegram auth data")

    telegram_id = int(data["id"])
    is_admin = (telegram_id == settings.SUPER_ADMIN_TELEGRAM_ID)

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=telegram_id,
            username=data.get("username"),
            avatar_url=data.get("photo_url"),
            status="approved" if is_admin else "pending",
            is_admin=is_admin,
        )
        db.add(user)
    else:
        user.username = data.get("username", user.username)
        user.avatar_url = data.get("photo_url", user.avatar_url)
        if is_admin:
            user.status = "approved"
            user.is_admin = True

    await db.commit()
    await db.refresh(user)

    # Notify admin if this user is still pending and hasn't been notified yet
    if user.status == "pending" and not user.notified_admin:
        await _notify_admin(user)
        user.notified_admin = True
        await db.commit()

    return {
        "token": create_jwt(user.id),
        "user_id": user.id,
        "username": user.username,
        "status": user.status,
        "is_admin": user.is_admin,
    }


@router.get("/status")
async def check_status(current_user: User = Depends(get_current_user)):
    """Accessible by all authenticated users including pending — used for polling."""
    return {"status": current_user.status, "username": current_user.username}


@router.post("/request-access")
async def request_access(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rejected users re-request access; re-notifies admin."""
    if current_user.status not in ("pending", "rejected"):
        raise HTTPException(400, "Only pending or rejected users can request access")
    current_user.status = "pending"
    current_user.notified_admin = False
    await db.commit()
    await _notify_admin(current_user)
    current_user.notified_admin = True
    await db.commit()
    return {"ok": True}
