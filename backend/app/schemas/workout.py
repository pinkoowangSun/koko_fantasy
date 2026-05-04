from datetime import date, datetime
from typing import Optional, Any
from pydantic import BaseModel


class WorkoutLogCreate(BaseModel):
    raw_text: str
    log_date: Optional[date] = None
    source: str = "web"


class WorkoutLogOut(BaseModel):
    id: int
    log_date: date
    raw_text: str
    category: Optional[str]
    summary: Optional[str]
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkoutPlanOut(BaseModel):
    id: int
    week_start: date
    plan: dict[str, Any]
    ai_notes: Optional[str]
    generated_at: datetime

    model_config = {"from_attributes": True}
