from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, DateTime, Date, Float, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.database import Base


class WorkoutLog(Base):
    __tablename__ = "workout_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    log_date = Column(Date, nullable=False, default=date.today, index=True)
    raw_text = Column(Text, nullable=False)
    category = Column(String, nullable=True)   # cardio | upper_body | lower_body | core | flexibility | mixed | rest
    summary = Column(Text, nullable=True)       # AI-generated concise summary
    duration_min = Column(Integer, nullable=True)  # AI-extracted total session duration
    source = Column(String, default="web")      # web | telegram
    created_at = Column(DateTime, default=datetime.utcnow)

    exercises = relationship("WorkoutExercise", back_populates="log", cascade="all, delete-orphan", lazy="select")


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"

    id = Column(Integer, primary_key=True, autoincrement=True)
    log_id = Column(Integer, ForeignKey("workout_logs.id"), nullable=False, index=True)
    exercise_name = Column(String, nullable=False)
    sets = Column(Integer, nullable=True)
    reps = Column(String, nullable=True)        # "8–10", "AMRAP", "30 sec"
    weight_kg = Column(Float, nullable=True)
    notes = Column(String, nullable=True)
    source = Column(String, default="user")     # "ai" (auto-extracted) | "user" (manually added)
    created_at = Column(DateTime, default=datetime.utcnow)

    log = relationship("WorkoutLog", back_populates="exercises")


class WorkoutPlan(Base):
    __tablename__ = "workout_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    week_start = Column(Date, nullable=False, index=True)   # Monday of the week
    plan = Column(JSON, nullable=False)                     # {monday: {...}, tuesday: {...}, ...}
    ai_notes = Column(Text, nullable=True)                  # AI rationale for the plan
    generated_at = Column(DateTime, default=datetime.utcnow)
