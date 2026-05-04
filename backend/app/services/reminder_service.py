import httpx
from datetime import date, datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.reminder import Reminder
from app.models.user import User
from app.models.workout import WorkoutPlan

scheduler = AsyncIOScheduler()


async def _send_telegram(telegram_id: int, text: str):
    from app.config import settings
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": telegram_id, "text": text},
        )


async def check_and_send_reminders():
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Reminder, User)
            .join(User, Reminder.user_id == User.id)
            .where(Reminder.sent.is_(False))
            .where(Reminder.remind_at <= now)
        )
        rows = result.all()
        for reminder, user in rows:
            try:
                await _send_telegram(user.telegram_id, f"⏰ Reminder: {reminder.message}")
                reminder.sent = True
            except Exception as exc:
                print(f"[reminder] failed to send #{reminder.id}: {exc}")
        await db.commit()


async def send_workout_reminders():
    today = date.today()
    day_name = today.strftime("%A").lower()
    week_start = today - timedelta(days=today.weekday())

    async with AsyncSessionLocal() as db:
        users = (await db.execute(
            select(User).where(User.telegram_id.isnot(None))
        )).scalars().all()

        for user in users:
            try:
                plan_row = (await db.execute(
                    select(WorkoutPlan).where(
                        WorkoutPlan.user_id == user.id,
                        WorkoutPlan.week_start == week_start,
                    )
                )).scalar_one_or_none()

                if not plan_row:
                    continue

                day_plan = plan_row.plan.get(day_name)
                if not day_plan:
                    continue

                focus = day_plan.get("focus", "Workout")
                exercises = day_plan.get("exercises") or []
                duration = day_plan.get("duration_min", 0)
                warmup = day_plan.get("warmup", "")
                notes = day_plan.get("notes", "")

                if not exercises or "rest" in focus.lower():
                    msg = f"🌅 Good morning! Today is a rest day.\n💡 {notes}" if notes else "🌅 Good morning! Rest day today — recharge well."
                else:
                    lines = [f"💪 Good morning! Today's workout — *{focus}*"]
                    if warmup:
                        lines.append(f"🔥 Warm-up: {warmup}")
                    for ex in exercises[:6]:
                        name = ex.get("name", "")
                        sets = ex.get("sets", "")
                        reps = ex.get("reps", "")
                        weight = ex.get("weight", "")
                        detail = f"{sets}×{reps}" if sets and reps else reps or sets
                        weight_str = f" @ {weight}" if weight and weight not in ("bodyweight", "") else (" (bodyweight)" if weight == "bodyweight" else "")
                        lines.append(f"  • {name}: {detail}{weight_str}")
                    if duration:
                        lines.append(f"⏱ ~{duration} min")
                    if notes:
                        lines.append(f"📝 {notes}")
                    msg = "\n".join(lines)

                await _send_telegram(user.telegram_id, msg)
            except Exception as exc:
                print(f"[workout reminder] failed for user {user.id}: {exc}")


def start_scheduler():
    scheduler.add_job(check_and_send_reminders, "interval", minutes=1, id="reminders")
    scheduler.add_job(send_workout_reminders, "cron", hour=8, minute=0, id="workout_reminders")
    scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
