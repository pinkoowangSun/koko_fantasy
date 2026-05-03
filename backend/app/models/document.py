from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from app.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    stored_name = Column(String, nullable=False)    # UUID-based on-disk filename
    original_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    source = Column(String, default="web")          # telegram | web
    indexed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
