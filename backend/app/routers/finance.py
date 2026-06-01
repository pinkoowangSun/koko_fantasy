"""Finance API — goals, assets, transactions, insights, daily summary."""
import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.finance import Asset, FinanceGoal, Transaction
from app.models.user import User
from app.routers.auth import require_approved
from app.schemas.finance import (
    AssetCreate, AssetOut, AssetUpdate,
    FinanceDailyOut, FinanceGoalCreate, FinanceGoalOut, FinanceGoalUpdate,
    FinanceInsightsOut, FinanceSummaryOut,
    TransactionCreate, TransactionOut, TransactionUpdate,
)
from app.services.ai_service import generate_finance_insights
from app.services.security import decrypt_amount, encrypt_amount

router = APIRouter(prefix="/finance", tags=["finance"])


# ── Goal progress helpers ─────────────────────────────────────────────────────

def _compute_goal_progress(
    goal: FinanceGoal,
    all_transactions: list[Transaction],
) -> tuple[float, float, str, Optional[str]]:
    """
    Returns (current_amount, progress_pct, status_label, projected_end_iso).
    status_label: 'on_track' | 'beyond' | 'at_risk'
    """
    today = date.today()

    # Filter transactions by goal currency and since goal creation
    goal_start = goal.created_at.date() if goal.created_at else today
    relevant = [
        t for t in all_transactions
        if t.currency == goal.currency and t.transaction_date >= goal_start
    ]

    if goal.goal_type == "spending_limit":
        # Current month spending vs limit
        month_start = today.replace(day=1)
        spent = sum(t.amount for t in relevant if t.transaction_type == "expense" and t.transaction_date >= month_start)
        current = goal.manual_current if goal.manual_current is not None else spent
        progress_pct = min((current / goal.target_amount) * 100, 100) if goal.target_amount else 0

        days_in_month = calendar.monthrange(today.year, today.month)[1]
        day_of_month = today.day
        expected_pace = goal.target_amount * (day_of_month / days_in_month)

        if current > goal.target_amount:
            status = "at_risk"
        elif current < expected_pace * 0.8:
            status = "beyond"
        else:
            status = "on_track"

        return current, progress_pct, status, None

    elif goal.goal_type == "saving_target":
        # Net savings since goal start
        income_total = sum(t.amount for t in relevant if t.transaction_type == "income")
        expense_total = sum(t.amount for t in relevant if t.transaction_type == "expense")
        auto_current = income_total - expense_total
        current = goal.manual_current if goal.manual_current is not None else auto_current
        progress_pct = min((current / goal.target_amount) * 100, 100) if goal.target_amount else 0

        # Monthly savings rate from last 3 months
        three_months_ago = today - timedelta(days=90)
        recent = [t for t in relevant if t.transaction_date >= three_months_ago]
        r_income = sum(t.amount for t in recent if t.transaction_type == "income")
        r_expense = sum(t.amount for t in recent if t.transaction_type == "expense")
        monthly_rate = (r_income - r_expense) / 3.0

        remaining = goal.target_amount - current
        projected_end: Optional[str] = None

        if monthly_rate <= 0:
            status = "at_risk"
        else:
            months_needed = remaining / monthly_rate
            proj_date = today + timedelta(days=int(months_needed * 30.44))
            projected_end = proj_date.isoformat()

            if goal.deadline:
                if proj_date <= goal.deadline - timedelta(days=int((goal.deadline - today).days * 0.15)):
                    status = "beyond"
                elif proj_date <= goal.deadline:
                    status = "on_track"
                else:
                    status = "at_risk"
            else:
                # No deadline: at_risk if monthly_rate < target/36 (3-year baseline)
                status = "on_track" if monthly_rate >= goal.target_amount / 36 else "at_risk"

        return current, progress_pct, status, projected_end

    else:
        # income_target or custom: simple progress against manual_current
        current = goal.manual_current or 0.0
        progress_pct = min((current / goal.target_amount) * 100, 100) if goal.target_amount else 0
        if goal.deadline:
            status = "on_track" if today <= goal.deadline else "at_risk"
        else:
            status = "on_track"
        return current, progress_pct, status, None


def _goal_to_out(goal: FinanceGoal, transactions: list[Transaction]) -> FinanceGoalOut:
    current, pct, status_label, projected_end = _compute_goal_progress(goal, transactions)
    return FinanceGoalOut(
        id=goal.id,
        title=goal.title,
        description=goal.description,
        goal_type=goal.goal_type,
        term=goal.term,
        target_amount=goal.target_amount,
        currency=goal.currency,
        deadline=goal.deadline,
        manual_current=goal.manual_current,
        status=goal.status,
        created_at=goal.created_at.isoformat() if goal.created_at else "",
        current_amount=round(current, 2),
        progress_pct=round(pct, 1),
        status_label=status_label,
        projected_end=projected_end,
    )


# ── Goals ─────────────────────────────────────────────────────────────────────

@router.get("/goals", response_model=list[FinanceGoalOut])
async def list_goals(
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    goals = (await db.execute(
        select(FinanceGoal)
        .where(FinanceGoal.user_id == current_user.id)
        .order_by(FinanceGoal.created_at.desc())
    )).scalars().all()

    transactions = (await db.execute(
        select(Transaction).where(Transaction.user_id == current_user.id)
    )).scalars().all()

    return [_goal_to_out(g, transactions) for g in goals]


@router.post("/goals", response_model=FinanceGoalOut, status_code=201)
async def create_goal(
    body: FinanceGoalCreate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    goal = FinanceGoal(
        user_id=current_user.id,
        title=body.title,
        description=body.description,
        goal_type=body.goal_type,
        term=body.term,
        target_amount=body.target_amount,
        currency=body.currency.upper(),
        deadline=body.deadline,
        manual_current=body.manual_current,
        status=body.status,
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)

    transactions = (await db.execute(
        select(Transaction).where(Transaction.user_id == current_user.id)
    )).scalars().all()
    return _goal_to_out(goal, transactions)


@router.patch("/goals/{goal_id}", response_model=FinanceGoalOut)
async def update_goal(
    goal_id: int,
    body: FinanceGoalUpdate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    goal = (await db.execute(
        select(FinanceGoal).where(FinanceGoal.id == goal_id, FinanceGoal.user_id == current_user.id)
    )).scalar_one_or_none()
    if not goal:
        raise HTTPException(404, "Goal not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    if "currency" in body.model_dump(exclude_unset=True) and body.currency:
        goal.currency = body.currency.upper()
    goal.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(goal)

    transactions = (await db.execute(
        select(Transaction).where(Transaction.user_id == current_user.id)
    )).scalars().all()
    return _goal_to_out(goal, transactions)


@router.delete("/goals/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    goal = (await db.execute(
        select(FinanceGoal).where(FinanceGoal.id == goal_id, FinanceGoal.user_id == current_user.id)
    )).scalar_one_or_none()
    if not goal:
        raise HTTPException(404, "Goal not found")
    await db.delete(goal)
    await db.commit()


# ── Assets ────────────────────────────────────────────────────────────────────

def _asset_to_out(asset: Asset) -> AssetOut:
    try:
        amount = decrypt_amount(asset.amount_encrypted)
    except Exception:
        amount = 0.0
    return AssetOut(
        id=asset.id,
        name=asset.name,
        asset_type=asset.asset_type,
        amount=round(amount, 2),
        currency=asset.currency,
        institution=asset.institution,
        notes=asset.notes,
        created_at=asset.created_at.isoformat() if asset.created_at else "",
    )


@router.get("/assets", response_model=list[AssetOut])
async def list_assets(
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    assets = (await db.execute(
        select(Asset)
        .where(Asset.user_id == current_user.id)
        .order_by(Asset.asset_type.asc(), Asset.name.asc())
    )).scalars().all()
    return [_asset_to_out(a) for a in assets]


@router.post("/assets", response_model=AssetOut, status_code=201)
async def create_asset(
    body: AssetCreate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    if not body.amount >= 0:
        raise HTTPException(400, "Amount must be non-negative")
    encrypted = encrypt_amount(body.amount)
    asset = Asset(
        user_id=current_user.id,
        name=body.name,
        asset_type=body.asset_type,
        amount_encrypted=encrypted,
        currency=body.currency.upper(),
        institution=body.institution,
        notes=body.notes,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return _asset_to_out(asset)


@router.patch("/assets/{asset_id}", response_model=AssetOut)
async def update_asset(
    asset_id: int,
    body: AssetUpdate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    asset = (await db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == current_user.id)
    )).scalar_one_or_none()
    if not asset:
        raise HTTPException(404, "Asset not found")

    updates = body.model_dump(exclude_unset=True)
    if "amount" in updates:
        asset.amount_encrypted = encrypt_amount(updates.pop("amount"))
    if "currency" in updates:
        updates["currency"] = updates["currency"].upper()
    for field, value in updates.items():
        setattr(asset, field, value)
    asset.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(asset)
    return _asset_to_out(asset)


@router.delete("/assets/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    asset = (await db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == current_user.id)
    )).scalar_one_or_none()
    if not asset:
        raise HTTPException(404, "Asset not found")
    await db.delete(asset)
    await db.commit()


@router.get("/assets/{asset_id}/trend")
async def get_asset_trend(
    asset_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    asset = (await db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == current_user.id)
    )).scalar_one_or_none()
    if not asset:
        raise HTTPException(404, "Asset not found")

    try:
        current_amount = decrypt_amount(asset.amount_encrypted)
    except Exception:
        current_amount = 0.0

    txs = (await db.execute(
        select(Transaction)
        .where(Transaction.user_id == current_user.id, Transaction.currency == asset.currency)
        .order_by(Transaction.transaction_date.asc())
    )).scalars().all()

    # Group net change by month
    monthly_net: dict[str, float] = defaultdict(float)
    for t in txs:
        month = t.transaction_date.strftime("%Y-%m")
        if t.transaction_type == "income":
            monthly_net[month] += t.amount
        elif t.transaction_type == "expense":
            monthly_net[month] -= t.amount

    months = sorted(monthly_net.keys())

    # Reconstruct historical balances from current amount working backwards
    total_net = sum(monthly_net.values())
    baseline = current_amount - total_net

    result = []
    running = baseline
    for month in months:
        running += monthly_net[month]
        result.append({
            "month": month,
            "balance": round(running, 2),
            "net_change": round(monthly_net[month], 2),
        })

    # Ensure current month appears with the actual current balance
    today_month = date.today().strftime("%Y-%m")
    if today_month not in monthly_net:
        result.append({"month": today_month, "balance": round(current_amount, 2), "net_change": 0.0})

    return {"currency": asset.currency, "name": asset.name, "monthly": result}


# ── Transactions ──────────────────────────────────────────────────────────────

def _tx_to_out(t: Transaction) -> TransactionOut:
    return TransactionOut(
        id=t.id,
        amount=t.amount,
        transaction_type=t.transaction_type,
        category=t.category,
        currency=t.currency,
        description=t.description,
        transaction_date=t.transaction_date.isoformat() if t.transaction_date else "",
        source=t.source,
        created_at=t.created_at.isoformat() if t.created_at else "",
    )


@router.get("/transactions", response_model=list[TransactionOut])
async def list_transactions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    transaction_type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    limit: int = Query(default=100, le=500),
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    q = select(Transaction).where(Transaction.user_id == current_user.id)
    if start_date:
        q = q.where(Transaction.transaction_date >= start_date)
    if end_date:
        q = q.where(Transaction.transaction_date <= end_date)
    if transaction_type:
        q = q.where(Transaction.transaction_type == transaction_type)
    if category:
        q = q.where(Transaction.category == category)
    if currency:
        q = q.where(Transaction.currency == currency.upper())
    q = q.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).limit(limit)
    txs = (await db.execute(q)).scalars().all()
    return [_tx_to_out(t) for t in txs]


@router.post("/transactions", response_model=TransactionOut, status_code=201)
async def create_transaction(
    body: TransactionCreate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    tx = Transaction(
        user_id=current_user.id,
        amount=body.amount,
        transaction_type=body.transaction_type,
        category=body.category,
        currency=body.currency.upper(),
        description=body.description,
        transaction_date=body.transaction_date or date.today(),
        source="web",
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    return _tx_to_out(tx)


@router.patch("/transactions/{tx_id}", response_model=TransactionOut)
async def update_transaction(
    tx_id: int,
    body: TransactionUpdate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    tx = (await db.execute(
        select(Transaction).where(Transaction.id == tx_id, Transaction.user_id == current_user.id)
    )).scalar_one_or_none()
    if not tx:
        raise HTTPException(404, "Transaction not found")

    updates = body.model_dump(exclude_unset=True)
    if "currency" in updates and updates["currency"]:
        updates["currency"] = updates["currency"].upper()
    for field, value in updates.items():
        setattr(tx, field, value)
    tx.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(tx)
    return _tx_to_out(tx)


@router.delete("/transactions/{tx_id}", status_code=204)
async def delete_transaction(
    tx_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    tx = (await db.execute(
        select(Transaction).where(Transaction.id == tx_id, Transaction.user_id == current_user.id)
    )).scalar_one_or_none()
    if not tx:
        raise HTTPException(404, "Transaction not found")
    await db.delete(tx)
    await db.commit()


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=FinanceSummaryOut)
async def get_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    q = select(Transaction).where(Transaction.user_id == current_user.id)
    if start_date:
        q = q.where(Transaction.transaction_date >= start_date)
    if end_date:
        q = q.where(Transaction.transaction_date <= end_date)
    txs = (await db.execute(q)).scalars().all()

    income_by_currency: dict[str, float] = defaultdict(float)
    expense_by_currency: dict[str, float] = defaultdict(float)
    by_category: dict[str, float] = defaultdict(float)

    for t in txs:
        if t.transaction_type == "income":
            income_by_currency[t.currency] += t.amount
        elif t.transaction_type == "expense":
            expense_by_currency[t.currency] += t.amount
            by_category[t.category] += t.amount

    all_currencies = set(income_by_currency) | set(expense_by_currency)
    net_by_currency = {
        c: round(income_by_currency.get(c, 0) - expense_by_currency.get(c, 0), 2)
        for c in all_currencies
    }

    return FinanceSummaryOut(
        income_by_currency={k: round(v, 2) for k, v in income_by_currency.items()},
        expense_by_currency={k: round(v, 2) for k, v in expense_by_currency.items()},
        net_by_currency=net_by_currency,
        by_category={k: round(v, 2) for k, v in by_category.items()},
        transaction_count=len(txs),
    )


# ── Daily (for calendar / dashboard widget) ───────────────────────────────────

@router.get("/daily", response_model=FinanceDailyOut)
async def get_daily(
    query_date: Optional[date] = Query(None, alias="date"),
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    target = query_date or date.today()
    txs = (await db.execute(
        select(Transaction)
        .where(Transaction.user_id == current_user.id, Transaction.transaction_date == target)
        .order_by(Transaction.created_at.desc())
    )).scalars().all()

    income_by_currency: dict[str, float] = defaultdict(float)
    expense_by_currency: dict[str, float] = defaultdict(float)

    for t in txs:
        if t.transaction_type == "income":
            income_by_currency[t.currency] += t.amount
        elif t.transaction_type == "expense":
            expense_by_currency[t.currency] += t.amount

    return FinanceDailyOut(
        date=target.isoformat(),
        income_by_currency={k: round(v, 2) for k, v in income_by_currency.items()},
        expense_by_currency={k: round(v, 2) for k, v in expense_by_currency.items()},
        transactions=[_tx_to_out(t) for t in txs],
    )


# ── AI Insights ───────────────────────────────────────────────────────────────

@router.get("/insights", response_model=FinanceInsightsOut)
async def get_insights(
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    thirty_ago = date.today() - timedelta(days=30)
    txs = (await db.execute(
        select(Transaction)
        .where(Transaction.user_id == current_user.id, Transaction.transaction_date >= thirty_ago)
        .order_by(Transaction.transaction_date.asc())
    )).scalars().all()

    goals = (await db.execute(
        select(FinanceGoal)
        .where(FinanceGoal.user_id == current_user.id, FinanceGoal.status == "active")
    )).scalars().all()

    tx_data = [
        {
            "date": t.transaction_date.isoformat(),
            "type": t.transaction_type,
            "amount": t.amount,
            "currency": t.currency,
            "category": t.category,
            "description": t.description or "",
        }
        for t in txs
    ]
    goal_data = [
        {"title": g.title, "type": g.goal_type, "target": g.target_amount, "currency": g.currency}
        for g in goals
    ]

    result = await generate_finance_insights(current_user.id, {"transactions": tx_data, "goals": goal_data})
    return FinanceInsightsOut(**result)
