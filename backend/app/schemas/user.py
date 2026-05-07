from pydantic import BaseModel, field_validator
from typing import Optional, Dict, Any
from datetime import datetime


class UserUpdate(BaseModel):
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    timezone: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, KeyError):
            raise ValueError(f"Invalid timezone: {v!r}")
        return v


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
