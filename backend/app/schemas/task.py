from pydantic import BaseModel, model_validator
from typing import Optional, List
from datetime import datetime, timedelta


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    status: str = "todo"
    priority: str = "medium"
    due_date: Optional[datetime] = None
    reminder_at: Optional[datetime] = None
    tags: List[str] = []

    @model_validator(mode="after")
    def set_reminder_default(self):
        if self.due_date and self.reminder_at is None:
            self.reminder_at = self.due_date - timedelta(days=1)
        return self


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[datetime] = None
    reminder_at: Optional[datetime] = None
    tags: Optional[List[str]] = None


class TaskResponse(BaseModel):
    id: int
    user_id: int
    title: str
    description: Optional[str]
    status: str
    priority: str
    due_date: Optional[datetime]
    reminder_at: Optional[datetime]
    tags: List[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
