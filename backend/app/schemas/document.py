from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class DocumentResponse(BaseModel):
    id: int
    user_id: int
    stored_name: str
    original_name: str
    file_size: Optional[int]
    mime_type: Optional[str]
    description: Optional[str]
    source: str
    indexed: bool
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentQARequest(BaseModel):
    question: str
    document_id: Optional[int] = None  # None = search all user docs
