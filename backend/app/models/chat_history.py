from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.database import Base


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, nullable=False)    # user | assistant | system
    content = Column(Text, nullable=False)
    source = Column(String, default="telegram")  # telegram | web
    created_at = Column(DateTime, default=datetime.utcnow)
