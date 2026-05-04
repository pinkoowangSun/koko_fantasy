from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, DateTime, Date, ForeignKey, JSON
from app.database import Base


class WorkoutLog(Base):
    __tablename__ = "workout_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    log_date = Column(Date, nullable=False, default=date.today, index=True)
    raw_text = Column(Text, nullable=False)
    category = Column(String, nullable=True)   # cardio | upper_body | lower_body | core | flexibility | mixed | rest
    summary = Column(Text, nullable=True)       # AI-generated concise summary
    source = Column(String, default="web")      # web | telegram
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkoutPlan(Base):
    __tablename__ = "workout_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    week_start = Column(Date, nullable=False, index=True)   # Monday of the week
    plan = Column(JSON, nullable=False)                     # {monday: {...}, tuesday: {...}, ...}
    ai_notes = Column(Text, nullable=True)                  # AI rationale for the plan
    generated_at = Column(DateTime, default=datetime.utcnow)
