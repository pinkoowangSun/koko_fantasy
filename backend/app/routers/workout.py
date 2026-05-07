from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.memory import MemoryItem
from app.models.user import User
from app.models.workout import WorkoutExercise, WorkoutLog, WorkoutPlan
from app.routers.auth import require_approved
from app.schemas.workout import (
    WorkoutExerciseCreate,
    WorkoutExerciseOut,
    WorkoutInsightsOut,
    WorkoutLogCreate,
    WorkoutLogOut,
    WorkoutLogUpdate,
    WorkoutPlanOut,
)
from app.services.ai_service import generate_workout_insights, generate_workout_plan, parse_workout_log

router = APIRouter(prefix="/workout", tags=["workout"])


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


@router.get("/logs", response_model=list[WorkoutLogOut])
async def list_logs(
    limit: int = 50,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    logs = (await db.execute(
        select(WorkoutLog)
        .options(selectinload(WorkoutLog.exercises))
        .where(WorkoutLog.user_id == current_user.id)
        .order_by(WorkoutLog.log_date.desc(), WorkoutLog.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return logs


@router.post("/logs", response_model=WorkoutLogOut)
async def create_log(
    body: WorkoutLogCreate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    parsed = await parse_workout_log(current_user.id, body.raw_text)
    log = WorkoutLog(
        user_id=current_user.id,
        log_date=body.log_date or date.today(),
        raw_text=body.raw_text,
        category=parsed.get("category"),
        summary=parsed.get("summary"),
        duration_min=parsed.get("duration_min"),
        calories_burnt=parsed.get("calories_burnt"),
        source=body.source,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    for ex in parsed.get("exercises") or []:
        name = (ex.get("exercise_name") or "").strip()
        if not name:
            continue
        db.add(WorkoutExercise(
            log_id=log.id,
            exercise_name=name,
            sets=ex.get("sets"),
            reps=ex.get("reps") or None,
            weight_kg=ex.get("weight_kg"),
            notes=ex.get("notes") or None,
            source="ai",
        ))
    await db.commit()

    log = (await db.execute(
        select(WorkoutLog).options(selectinload(WorkoutLog.exercises)).where(WorkoutLog.id == log.id)
    )).scalar_one()
    return log


@router.patch("/logs/{log_id}", response_model=WorkoutLogOut)
async def update_log(
    log_id: int,
    body: WorkoutLogUpdate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    log = (await db.execute(
        select(WorkoutLog).where(
            WorkoutLog.id == log_id,
            WorkoutLog.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Workout log not found")

    if body.log_date is not None:
        log.log_date = body.log_date
    if body.raw_text is not None and body.raw_text != log.raw_text:
        log.raw_text = body.raw_text
        parsed = await parse_workout_log(current_user.id, body.raw_text)
        log.category = parsed.get("category")
        log.summary = parsed.get("summary")
        log.duration_min = parsed.get("duration_min")
        log.calories_burnt = parsed.get("calories_burnt")

        # Replace previously AI-extracted exercises with fresh parse
        old_ai = (await db.execute(
            select(WorkoutExercise).where(
                WorkoutExercise.log_id == log.id,
                WorkoutExercise.source == "ai",
            )
        )).scalars().all()
        for ex in old_ai:
            await db.delete(ex)

        for ex in parsed.get("exercises") or []:
            name = (ex.get("exercise_name") or "").strip()
            if not name:
                continue
            db.add(WorkoutExercise(
                log_id=log.id,
                exercise_name=name,
                sets=ex.get("sets"),
                reps=ex.get("reps") or None,
                weight_kg=ex.get("weight_kg"),
                notes=ex.get("notes") or None,
                source="ai",
            ))

    await db.commit()
    log = (await db.execute(
        select(WorkoutLog).options(selectinload(WorkoutLog.exercises)).where(WorkoutLog.id == log_id)
    )).scalar_one()
    return log


@router.delete("/logs/{log_id}", status_code=204)
async def delete_log(
    log_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    log = (await db.execute(
        select(WorkoutLog).where(
            WorkoutLog.id == log_id,
            WorkoutLog.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Workout log not found")
    await db.delete(log)
    await db.commit()


@router.delete("/logs/{log_id}/exercises/{exercise_id}", status_code=204)
async def delete_exercise(
    log_id: int,
    exercise_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    ex = (await db.execute(
        select(WorkoutExercise)
        .join(WorkoutLog, WorkoutLog.id == WorkoutExercise.log_id)
        .where(
            WorkoutExercise.id == exercise_id,
            WorkoutExercise.log_id == log_id,
            WorkoutLog.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if not ex:
        raise HTTPException(status_code=404, detail="Exercise not found")
    await db.delete(ex)
    await db.commit()


@router.post("/logs/{log_id}/exercises", response_model=WorkoutExerciseOut)
async def add_exercise(
    log_id: int,
    body: WorkoutExerciseCreate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    log = (await db.execute(
        select(WorkoutLog).where(
            WorkoutLog.id == log_id,
            WorkoutLog.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Workout log not found")

    exercise = WorkoutExercise(log_id=log_id, **body.model_dump())
    db.add(exercise)
    await db.commit()
    await db.refresh(exercise)
    return exercise


@router.get("/plan", response_model=Optional[WorkoutPlanOut])
async def get_plan(
    current_user: User = Depends(require_approved),
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
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    four_weeks_ago = date.today() - timedelta(weeks=4)
    logs = (await db.execute(
        select(WorkoutLog)
        .options(selectinload(WorkoutLog.exercises))
        .where(
            WorkoutLog.user_id == current_user.id,
            WorkoutLog.log_date >= four_weeks_ago,
        )
        .order_by(WorkoutLog.log_date.asc())
    )).scalars().all()

    # Build rich logs context including structured exercises when available
    logs_context_parts = []
    for l in logs:
        line = f"[{l.log_date}] {l.category or 'unknown'}: {l.raw_text}"
        if l.exercises:
            ex_str = ", ".join(
                f"{e.exercise_name} {e.sets or '?'}x{e.reps or '?'}" +
                (f" @{e.weight_kg}kg" if e.weight_kg else "")
                for e in l.exercises
            )
            line += f" | Logged exercises: {ex_str}"
        logs_context_parts.append(line)
    logs_context = "\n".join(logs_context_parts) if logs_context_parts else ""

    memory_items = (await db.execute(
        select(MemoryItem).where(MemoryItem.user_id == current_user.id).limit(20)
    )).scalars().all()

    # Merge workout preference from both memory items and user.preferences JSON
    pref_from_memory = next((m.value for m in memory_items if m.key.strip().lower() == "workout"), "")
    pref_from_user = (current_user.preferences or {}).get("workout", "")
    workout_pref = "; ".join(filter(None, [pref_from_memory, pref_from_user]))

    user_memory = "; ".join(
        f"{m.key}: {m.value}"
        for m in memory_items
        if m.key.strip().lower() != "workout"
    )

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


@router.get("/insights", response_model=WorkoutInsightsOut)
async def get_insights(
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    eight_weeks_ago = date.today() - timedelta(weeks=8)
    logs = (await db.execute(
        select(WorkoutLog)
        .options(selectinload(WorkoutLog.exercises))
        .where(
            WorkoutLog.user_id == current_user.id,
            WorkoutLog.log_date >= eight_weeks_ago,
        )
        .order_by(WorkoutLog.log_date.asc())
    )).scalars().all()

    logs_data = []
    for l in logs:
        entry: dict = {
            "date": str(l.log_date),
            "category": l.category or "unknown",
            "summary": l.summary or l.raw_text[:150],
        }
        if l.exercises:
            entry["exercises"] = [
                {
                    "name": e.exercise_name,
                    "sets": e.sets,
                    "reps": e.reps,
                    "weight_kg": e.weight_kg,
                }
                for e in l.exercises
            ]
        logs_data.append(entry)

    return await generate_workout_insights(logs_data)
