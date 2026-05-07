from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


# ── Goals ─────────────────────────────────────────────────────────────────────

class FinanceGoalCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    goal_type: str = "saving_target"  # spending_limit | saving_target | income_target | custom
    term: str = "mid"                 # short | mid | long
    target_amount: float = Field(..., gt=0)
    currency: str = Field(default="SGD", max_length=10)
    deadline: Optional[date] = None
    manual_current: Optional[float] = None
    status: str = "active"


class FinanceGoalUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    goal_type: Optional[str] = None
    term: Optional[str] = None
    target_amount: Optional[float] = None
    currency: Optional[str] = None
    deadline: Optional[date] = None
    manual_current: Optional[float] = None
    status: Optional[str] = None


class FinanceGoalOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    title: str
    description: Optional[str]
    goal_type: str
    term: str
    target_amount: float
    currency: str
    deadline: Optional[date]
    manual_current: Optional[float]
    status: str
    created_at: str
    # Computed fields (added by router)
    current_amount: float = 0.0
    progress_pct: float = 0.0
    status_label: str = "on_track"       # on_track | beyond | at_risk
    projected_end: Optional[str] = None


# ── Assets ────────────────────────────────────────────────────────────────────

class AssetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    asset_type: str = "cash"  # cash | investment | property | crypto | cpf | other
    amount: float = Field(..., ge=0)
    currency: str = Field(default="SGD", max_length=10)
    institution: Optional[str] = None
    notes: Optional[str] = None


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    asset_type: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    institution: Optional[str] = None
    notes: Optional[str] = None


class AssetOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    asset_type: str
    amount: float        # decrypted
    currency: str
    institution: Optional[str]
    notes: Optional[str]
    created_at: str


# ── Transactions ──────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    amount: float = Field(..., gt=0)
    transaction_type: str  # income | expense | transfer
    category: str = "other"
    currency: str = Field(default="SGD", max_length=10)
    description: Optional[str] = None
    transaction_date: Optional[date] = None


class TransactionUpdate(BaseModel):
    amount: Optional[float] = None
    transaction_type: Optional[str] = None
    category: Optional[str] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    transaction_date: Optional[date] = None


class TransactionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    amount: float
    transaction_type: str
    category: str
    currency: str
    description: Optional[str]
    transaction_date: str
    source: str
    created_at: str


# ── Summary & Insights ────────────────────────────────────────────────────────

class FinanceSummaryOut(BaseModel):
    income_by_currency: dict[str, float]
    expense_by_currency: dict[str, float]
    net_by_currency: dict[str, float]
    by_category: dict[str, float]      # category → total expense amount (default currency mix)
    transaction_count: int


class FinanceInsightsOut(BaseModel):
    summary: str
    top_categories: list[str]
    income_trend: str
    expense_trend: str
    goal_status_note: str
    advice: list[str]


class FinanceDailyOut(BaseModel):
    date: str
    income_by_currency: dict[str, float]
    expense_by_currency: dict[str, float]
    transactions: list[TransactionOut]
