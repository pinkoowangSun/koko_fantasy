from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User
from app.routers.auth import require_approved
from app.schemas.task import TaskCreate, TaskResponse, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    q = select(Task).where(Task.user_id == current_user.id)
    if status:
        q = q.where(Task.status == status)
    if priority:
        q = q.where(Task.priority == priority)
    q = q.order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
    return (await db.execute(q)).scalars().all()


@router.post("/", response_model=TaskResponse, status_code=201)
async def create_task(
    body: TaskCreate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    task = Task(user_id=current_user.id, **body.model_dump())
    db.add(task)
    await db.flush()

    if task.reminder_at:
        db.add(Reminder(
            user_id=current_user.id,
            task_id=task.id,
            message=f"Task due: {task.title}",
            remind_at=task.reminder_at,
        ))

    await db.commit()
    await db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    body: TaskUpdate,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    updates = body.model_dump(exclude_none=True)
    for k, v in updates.items():
        setattr(task, k, v)
    task.updated_at = datetime.utcnow()

    if updates.get("status") in ("done", "cancelled"):
        pending = (await db.execute(
            select(Reminder).where(Reminder.task_id == task_id, Reminder.sent.is_(False))
        )).scalars().all()
        for r in pending:
            await db.delete(r)

    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: int,
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    linked = (await db.execute(
        select(Reminder).where(Reminder.task_id == task_id)
    )).scalars().all()
    for r in linked:
        await db.delete(r)

    await db.delete(task)
    await db.commit()
