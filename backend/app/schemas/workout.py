from datetime import date, datetime
from typing import Optional, Any
from pydantic import BaseModel, Field


class WorkoutExerciseCreate(BaseModel):
    exercise_name: str = Field(..., max_length=200)
    sets: Optional[int] = None
    reps: Optional[str] = Field(None, max_length=50)
    weight_kg: Optional[float] = None
    notes: Optional[str] = Field(None, max_length=500)


class WorkoutExerciseOut(BaseModel):
    id: int
    log_id: int
    exercise_name: str
    sets: Optional[int]
    reps: Optional[str]
    weight_kg: Optional[float]
    notes: Optional[str]
    source: str = "user"

    model_config = {"from_attributes": True}


class WorkoutLogCreate(BaseModel):
    raw_text: str = Field(..., max_length=5000)
    log_date: Optional[date] = None
    source: str = "web"


class WorkoutExerciseUpdate(BaseModel):
    exercise_name: Optional[str] = None
    sets: Optional[int] = None
    reps: Optional[str] = None
    weight_kg: Optional[float] = None
    notes: Optional[str] = None


class WorkoutLogUpdate(BaseModel):
    raw_text: Optional[str] = None
    log_date: Optional[date] = None
    duration_min: Optional[int] = None
    calories_burnt: Optional[int] = None


class WorkoutLogOut(BaseModel):
    id: int
    log_date: date
    raw_text: str
    category: Optional[str]
    summary: Optional[str]
    duration_min: Optional[int] = None
    calories_burnt: Optional[int] = None
    source: str
    created_at: datetime
    exercises: list[WorkoutExerciseOut] = []

    model_config = {"from_attributes": True}


class WorkoutPlanOut(BaseModel):
    id: int
    week_start: date
    plan: dict[str, Any]
    ai_notes: Optional[str]
    generated_at: datetime

    model_config = {"from_attributes": True}


class WorkoutInsightsOut(BaseModel):
    summary: str
    consistency: str
    strengths: list[str]
    improvements: list[str]
    trends: list[str]
    recommendations: list[str]
