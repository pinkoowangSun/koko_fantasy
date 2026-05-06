import logging
import httpx
from datetime import date, datetime, timedelta, timezone as _tz
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.reminder import Reminder
from app.models.user import User
from app.models.workout import WorkoutPlan

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

MORNING_HOUR = 8  # 8 AM in the user's local timezone


def _local_now(tz_str: str | None) -> datetime:
    """Return current time in the user's local timezone. Falls back to UTC."""
    now_utc = datetime.now(_tz.utc)
    try:
        return now_utc.astimezone(ZoneInfo(tz_str or "UTC"))
    except (ZoneInfoNotFoundError, Exception):
        return now_utc


async def _send_telegram(telegram_id: int, text: str):
    from app.config import settings
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": telegram_id, "text": text, "parse_mode": "Markdown"},
        )
        resp.raise_for_status()


async def check_and_send_reminders():
    now = datetime.utcnow()
    try:
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
                    await _send_telegram(user.telegram_id, f"⏰ *Reminder*\n{reminder.message}")
                    reminder.sent = True
                    log.info("[reminders] sent #%d to telegram_id=%s", reminder.id, user.telegram_id)
                except Exception as exc:
                    log.error("[reminders] failed to send #%d: %s", reminder.id, exc)
            if rows:
                await db.commit()
    except Exception as exc:
        log.error("[reminders] check_and_send_reminders crashed: %s", exc)


async def send_workout_reminders():
    """
    Runs every minute. For each approved user, sends their morning workout
    summary at exactly MORNING_HOUR:00 in *their* local timezone.
    """
    async with AsyncSessionLocal() as db:
        users = (await db.execute(
            select(User).where(
                User.telegram_id.isnot(None),
                User.status == "approved",
            )
        )).scalars().all()

        for user in users:
            try:
                local_now = _local_now(user.timezone)

                # Send only at the exact minute the user's local clock hits MORNING_HOUR:00
                if local_now.hour != MORNING_HOUR:
                    continue

                local_today = local_now.date()
                day_name = local_today.strftime("%A").lower()
                week_start = local_today - timedelta(days=local_today.weekday())

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
                    msg = (
                        f"🌅 Good morning! Today is a rest day.\n💡 {notes}"
                        if notes else
                        "🌅 Good morning! Rest day today — recharge well."
                    )
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
                        weight_str = (
                            " (bodyweight)" if weight == "bodyweight"
                            else f" @ {weight}" if weight else ""
                        )
                        lines.append(f"  • {name}: {detail}{weight_str}")
                    if duration:
                        lines.append(f"⏱ ~{duration} min")
                    if notes:
                        lines.append(f"📝 {notes}")
                    msg = "\n".join(lines)

                await _send_telegram(user.telegram_id, msg)
                log.info("[workout reminder] sent to user %d (tz=%s)", user.id, user.timezone)

            except Exception as exc:
                log.error("[workout reminder] failed for user %d: %s", user.id, exc)


def start_scheduler():
    scheduler.add_job(check_and_send_reminders, "interval", minutes=1, id="reminders",
                      misfire_grace_time=30)
    # Run every minute so each user is checked against their own local time
    scheduler.add_job(send_workout_reminders, "cron", minute=0, id="workout_reminders",
                      misfire_grace_time=60)
    scheduler.start()
    log.info("[scheduler] started — reminders every 1 min, workout briefing at %02d:00 local per user", MORNING_HOUR)


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
    log.info("[scheduler] stopped")
