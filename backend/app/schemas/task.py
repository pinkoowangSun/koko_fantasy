from pydantic import BaseModel, model_validator
from typing import Optional, List
from datetime import datetime, timedelta, timezone


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
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            due = self.due_date.replace(tzinfo=None) if self.due_date.tzinfo else self.due_date
            if due - now > timedelta(days=1):
                self.reminder_at = due - timedelta(days=1)
            else:
                self.reminder_at = due
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
