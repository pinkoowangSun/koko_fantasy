from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MemoryCreate(BaseModel):
    key: str
    value: str
    category: str = "general"


class MemoryUpdate(BaseModel):
    value: Optional[str] = None
    category: Optional[str] = None


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
