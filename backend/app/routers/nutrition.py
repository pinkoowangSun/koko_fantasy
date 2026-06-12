from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.food_log import FoodLog
from app.models.user import User
from app.models.workout import WorkoutLog
from app.routers.auth import require_approved
from app.schemas.nutrition import DaySummaryOut, FoodLogCreate, FoodLogOut, FoodLogUpdate
from app.services.ai_service import parse_food_text

router = APIRouter(prefix="/nutrition", tags=["nutrition"])

_UTC = ZoneInfo("UTC")


def _user_tz(user: User) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone or "UTC")
    except Exception:
        return _UTC


def _local_date(utc_dt: datetime, tz: ZoneInfo) -> date:
    return utc_dt.replace(tzinfo=_UTC).astimezone(tz).date()


def _to_out(log: FoodLog, tz: ZoneInfo) -> FoodLogOut:
    return FoodLogOut(
        id=log.id,
        logged_at=log.logged_at.isoformat(),
        log_date=str(_local_date(log.logged_at, tz)),
        description=log.caption,
        dish_name=log.dish_name,
        calories_kcal=log.calories_kcal,
        protein_g=log.protein_g,
        carbs_g=log.carbs_g,
        fat_g=log.fat_g,
        fiber_g=log.fiber_g,
    )


@router.get("/summary", response_model=list[DaySummaryOut])
async def nutrition_summary(
    days: int = 14,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    days = max(1, min(days, 90))
    tz = _user_tz(current_user)
    today = datetime.now(tz).date()
    start = today - timedelta(days=days - 1)

    by_day = {
        start + timedelta(days=i): {
            "calories_in": 0.0, "calories_out": 0.0,
            "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0,
            "meals": 0,
        }
        for i in range(days)
    }

    # Extra day of margin so timezone conversion never drops edge entries
    cutoff_utc = datetime.utcnow() - timedelta(days=days + 1)
    food = (await db.execute(
        select(FoodLog).where(
            FoodLog.user_id == current_user.id,
            FoodLog.is_food.is_(True),
            FoodLog.logged_at >= cutoff_utc,
        )
    )).scalars().all()
    for f in food:
        day = by_day.get(_local_date(f.logged_at, tz))
        if not day:
            continue
        day["calories_in"] += f.calories_kcal or 0
        day["protein_g"] += f.protein_g or 0
        day["carbs_g"] += f.carbs_g or 0
        day["fat_g"] += f.fat_g or 0
        day["fiber_g"] += f.fiber_g or 0
        day["meals"] += 1

    workouts = (await db.execute(
        select(WorkoutLog).where(
            WorkoutLog.user_id == current_user.id,
            WorkoutLog.log_date >= start,
            WorkoutLog.log_date <= today,
        )
    )).scalars().all()
    for w in workouts:
        day = by_day.get(w.log_date)
        if day:
            day["calories_out"] += w.calories_burnt or 0

    return [
        DaySummaryOut(
            date=str(d),
            calories_in=round(v["calories_in"], 1),
            calories_out=round(v["calories_out"], 1),
            net=round(v["calories_in"] - v["calories_out"], 1),
            protein_g=round(v["protein_g"], 1),
            carbs_g=round(v["carbs_g"], 1),
            fat_g=round(v["fat_g"], 1),
            fiber_g=round(v["fiber_g"], 1),
            meals=v["meals"],
        )
        for d, v in sorted(by_day.items())
    ]


@router.get("/logs", response_model=list[FoodLogOut])
async def list_food_logs(
    days: int = 30,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    days = max(1, min(days, 365))
    tz = _user_tz(current_user)
    cutoff_utc = datetime.utcnow() - timedelta(days=days + 1)
    logs = (await db.execute(
        select(FoodLog)
        .where(
            FoodLog.user_id == current_user.id,
            FoodLog.is_food.is_(True),
            FoodLog.logged_at >= cutoff_utc,
        )
        .order_by(FoodLog.logged_at.desc())
    )).scalars().all()
    return [_to_out(l, tz) for l in logs]


@router.post("/logs", response_model=FoodLogOut)
async def create_food_log(
    body: FoodLogCreate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    description = body.description.strip()
    if not description:
        raise HTTPException(422, "Description is required")

    result = await parse_food_text(current_user.id, description)
    if not result.get("is_food"):
        raise HTTPException(400, "That doesn't look like food — try describing the meal, e.g. 'chicken rice with extra egg'.")

    tz = _user_tz(current_user)
    logged_at = datetime.utcnow()
    if body.log_date:
        try:
            d = date.fromisoformat(body.log_date)
        except ValueError:
            raise HTTPException(422, "log_date must be YYYY-MM-DD")
        if d != datetime.now(tz).date():
            # backdated entry: store as noon local time on that day
            logged_at = datetime.combine(d, datetime.min.time().replace(hour=12), tzinfo=tz).astimezone(_UTC).replace(tzinfo=None)

    log = FoodLog(
        user_id=current_user.id,
        logged_at=logged_at,
        is_food=True,
        dish_name=result.get("dish_name"),
        calories_kcal=result.get("calories_kcal"),
        protein_g=result.get("protein_g"),
        carbs_g=result.get("carbs_g"),
        fat_g=result.get("fat_g"),
        fiber_g=result.get("fiber_g"),
        caption=description,
        source="web",
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return _to_out(log, tz)


@router.patch("/logs/{log_id}", response_model=FoodLogOut)
async def update_food_log(
    log_id: int,
    body: FoodLogUpdate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    log = (await db.execute(
        select(FoodLog).where(FoodLog.id == log_id, FoodLog.user_id == current_user.id)
    )).scalar_one_or_none()
    if not log:
        raise HTTPException(404, "Food log not found")

    data = body.model_dump(exclude_unset=True)
    description = (data.pop("description", None) or "").strip()
    if description and description != (log.caption or ""):
        result = await parse_food_text(current_user.id, description)
        if not result.get("is_food"):
            raise HTTPException(400, "That doesn't look like food — try describing the meal, e.g. 'chicken rice with extra egg'.")
        log.caption = description
        log.dish_name = result.get("dish_name")
        log.calories_kcal = result.get("calories_kcal")
        log.protein_g = result.get("protein_g")
        log.carbs_g = result.get("carbs_g")
        log.fat_g = result.get("fat_g")
        log.fiber_g = result.get("fiber_g")

    # explicit field edits apply on top of any re-analysis
    for field, value in data.items():
        setattr(log, field, value)
    await db.commit()
    await db.refresh(log)
    return _to_out(log, _user_tz(current_user))


@router.delete("/logs/{log_id}", status_code=204)
async def delete_food_log(
    log_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    log = (await db.execute(
        select(FoodLog).where(FoodLog.id == log_id, FoodLog.user_id == current_user.id)
    )).scalar_one_or_none()
    if not log:
        raise HTTPException(404, "Food log not found")
    await db.delete(log)
    await db.commit()
