from typing import Optional

from pydantic import BaseModel


class FoodLogCreate(BaseModel):
    description: str
    log_date: Optional[str] = None   # YYYY-MM-DD in the user's timezone; defaults to today


class FoodLogUpdate(BaseModel):
    description: Optional[str] = None   # when changed, AI re-analyses and overwrites the estimates
    dish_name: Optional[str] = None
    calories_kcal: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None


class FoodLogOut(BaseModel):
    id: int
    logged_at: str           # UTC ISO datetime
    log_date: str            # YYYY-MM-DD in the user's timezone
    description: Optional[str]   # original free-text / photo caption the AI analysed
    dish_name: Optional[str]
    calories_kcal: Optional[float]
    protein_g: Optional[float]
    carbs_g: Optional[float]
    fat_g: Optional[float]
    fiber_g: Optional[float]


class DaySummaryOut(BaseModel):
    date: str                # YYYY-MM-DD in the user's timezone
    calories_in: float
    calories_out: float
    net: float               # calories_in - calories_out
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    meals: int
