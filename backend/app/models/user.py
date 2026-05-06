from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, JSON, Boolean
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    timezone = Column(String, default="UTC")
    preferences = Column(JSON, default=dict)
    status = Column(String, default="approved")       # approved | pending | rejected
    is_admin = Column(Boolean, default=False)
    notified_admin = Column(Boolean, default=False)
    profile_summary = Column(Text, nullable=True)
    profile_summary_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
