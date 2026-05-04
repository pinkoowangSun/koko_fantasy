from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.memory import MemoryItem
from app.models.user import User
from app.models.workout import WorkoutLog, WorkoutPlan
from app.routers.auth import get_current_user
from app.schemas.workout import WorkoutLogCreate, WorkoutLogOut, WorkoutPlanOut
from app.services.ai_service import generate_workout_plan, parse_workout_log

router = APIRouter(prefix="/workout", tags=["workout"])


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


@router.get("/logs", response_model=list[WorkoutLogOut])
async def list_logs(
    limit: int = 30,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logs = (await db.execute(
        select(WorkoutLog)
        .where(WorkoutLog.user_id == current_user.id)
        .order_by(WorkoutLog.log_date.desc(), WorkoutLog.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return logs


@router.post("/logs", response_model=WorkoutLogOut)
async def create_log(
    body: WorkoutLogCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    parsed = await parse_workout_log(current_user.id, body.raw_text)
    log = WorkoutLog(
        user_id=current_user.id,
        log_date=body.log_date or date.today(),
        raw_text=body.raw_text,
        category=parsed.get("category"),
        summary=parsed.get("summary"),
        source=body.source,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


@router.get("/plan", response_model=Optional[WorkoutPlanOut])
async def get_plan(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws = _week_start(date.today())
    plan = (await db.execute(
        select(WorkoutPlan).where(
            WorkoutPlan.user_id == current_user.id,
            WorkoutPlan.week_start == ws,
        )
    )).scalar_one_or_none()
    return plan


@router.post("/plan/generate", response_model=WorkoutPlanOut)
async def generate_plan(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    four_weeks_ago = date.today() - timedelta(weeks=4)
    logs = (await db.execute(
        select(WorkoutLog)
        .where(
            WorkoutLog.user_id == current_user.id,
            WorkoutLog.log_date >= four_weeks_ago,
        )
        .order_by(WorkoutLog.log_date.asc())
    )).scalars().all()

    logs_context = "\n".join(
        f"[{l.log_date}] {l.category or 'unknown'}: {l.raw_text}"
        for l in logs
    ) if logs else ""

    memory_items = (await db.execute(
        select(MemoryItem).where(MemoryItem.user_id == current_user.id).limit(20)
    )).scalars().all()
    workout_pref = next((m.value for m in memory_items if m.key.strip().lower() == "workout"), "")
    user_memory = "; ".join(f"{m.key}: {m.value}" for m in memory_items if m.key.strip().lower() != "workout")

    result = await generate_workout_plan(current_user.id, logs_context, user_memory, workout_pref)

    ws = _week_start(date.today())
    existing = (await db.execute(
        select(WorkoutPlan).where(
            WorkoutPlan.user_id == current_user.id,
            WorkoutPlan.week_start == ws,
        )
    )).scalar_one_or_none()

    if existing:
        existing.plan = result.get("plan", {})
        existing.ai_notes = result.get("notes")
        existing.generated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(existing)
        return existing

    plan = WorkoutPlan(
        user_id=current_user.id,
        week_start=ws,
        plan=result.get("plan", {}),
        ai_notes=result.get("notes"),
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan
