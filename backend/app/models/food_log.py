from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.database import Base


class FoodLog(Base):
    __tablename__ = "food_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    logged_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_food = Column(Boolean, nullable=False, default=False)
    dish_name = Column(String, nullable=True)
    calories_kcal = Column(Float, nullable=True)
    protein_g = Column(Float, nullable=True)
    carbs_g = Column(Float, nullable=True)
    fat_g = Column(Float, nullable=True)
    fiber_g = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    caption = Column(String, nullable=True)
    source = Column(String, default="telegram")
