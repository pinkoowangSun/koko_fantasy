from datetime import datetime
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, Boolean
from app.database import Base


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    message = Column(Text, nullable=False)
    remind_at = Column(DateTime, nullable=False, index=True)
    sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
