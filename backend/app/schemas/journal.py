from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime, date


class JournalCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = Field(None, max_length=50000)
    content_html: Optional[str] = Field(None, max_length=100000)
    mood: Optional[Literal["great", "good", "neutral", "low", "stressed"]] = None
    entry_date: date
    source: str = "web"


class JournalUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = Field(None, max_length=50000)
    content_html: Optional[str] = Field(None, max_length=100000)
    mood: Optional[Literal["great", "good", "neutral", "low", "stressed"]] = None


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
