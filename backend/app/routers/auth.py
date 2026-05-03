import hashlib
import hmac
import time
from datetime import datetime, timedelta

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


@router.post("/telegram")
async def telegram_login(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    if not _verify_telegram_data(dict(data)):
        raise HTTPException(status_code=401, detail="Invalid Telegram auth data")

    telegram_id = int(data["id"])
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=telegram_id,
            username=data.get("username"),
            avatar_url=data.get("photo_url"),
        )
        db.add(user)
    else:
        user.username = data.get("username", user.username)
        user.avatar_url = data.get("photo_url", user.avatar_url)

    await db.commit()
    await db.refresh(user)
    return {"token": create_jwt(user.id), "user_id": user.id, "username": user.username}
