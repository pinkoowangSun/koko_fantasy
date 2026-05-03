from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date


class JournalCreate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    content_html: Optional[str] = None
    mood: Optional[str] = None
    entry_date: date
    source: str = "web"


class JournalUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    content_html: Optional[str] = None
    mood: Optional[str] = None


class JournalResponse(BaseModel):
    id: int
    user_id: int
    title: Optional[str]
    content: Optional[str]
    content_html: Optional[str]
    mood: Optional[str]
    entry_date: date
    source: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
