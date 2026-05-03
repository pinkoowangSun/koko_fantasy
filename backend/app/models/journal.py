from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, DateTime, Date, ForeignKey
from app.database import Base


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=True)
    content = Column(Text, nullable=True)       # plain text (Telegram source)
    content_html = Column(Text, nullable=True)  # rich text (Web UI source)
    mood = Column(String, nullable=True)
    entry_date = Column(Date, nullable=False, index=True)
    source = Column(String, default="web")      # telegram | web
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
