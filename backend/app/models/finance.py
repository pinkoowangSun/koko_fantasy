from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, DateTime, Date, Float, ForeignKey, LargeBinary
from app.database import Base


FINANCE_CATEGORIES = [
    "food", "grocery", "transport", "housing", "utilities",
    "entertainment", "health", "education", "gift", "shopping",
    "travel", "salary", "freelance", "investment", "other",
]


class FinanceGoal(Base):
    __tablename__ = "finance_goals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    goal_type = Column(String, nullable=False, default="saving_target")  # spending_limit | saving_target | income_target | custom
    term = Column(String, nullable=False, default="mid")                 # short | mid | long
    target_amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="SGD")
    deadline = Column(Date, nullable=True)
    manual_current = Column(Float, nullable=True)  # user override; if set, replaces auto-computed progress
    status = Column(String, nullable=False, default="active")  # active | achieved | abandoned
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Asset(Base):
    __tablename__ = "finance_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    asset_type = Column(String, nullable=False, default="cash")  # cash | investment | property | crypto | cpf | other
    amount_encrypted = Column(LargeBinary, nullable=False)        # Fernet-encrypted float
    currency = Column(String, nullable=False, default="SGD")
    institution = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Transaction(Base):
    __tablename__ = "finance_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)                          # always positive
    transaction_type = Column(String, nullable=False)               # income | expense | transfer
    category = Column(String, nullable=False, default="other")
    currency = Column(String, nullable=False, default="SGD")
    description = Column(Text, nullable=True)
    transaction_date = Column(Date, nullable=False, default=date.today, index=True)
    source = Column(String, nullable=False, default="web")          # web | telegram
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
