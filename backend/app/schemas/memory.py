from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


class MemoryCreate(BaseModel):
    key: str = Field(..., max_length=200)
    value: str = Field(..., max_length=5000)
    category: Literal["general", "preference", "fact", "note"] = "general"


class MemoryUpdate(BaseModel):
    value: Optional[str] = Field(None, max_length=5000)
    category: Optional[Literal["general", "preference", "fact", "note"]] = None


class MemoryResponse(BaseModel):
    id: int
    user_id: int
    key: str
    value: str
    category: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
