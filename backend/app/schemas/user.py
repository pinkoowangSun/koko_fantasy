from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class UserUpdate(BaseModel):
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    timezone: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None


class UserResponse(BaseModel):
    id: int
    telegram_id: int
    username: Optional[str]
    avatar_url: Optional[str]
    timezone: str
    preferences: Dict[str, Any]
    status: str = "approved"
    is_admin: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
