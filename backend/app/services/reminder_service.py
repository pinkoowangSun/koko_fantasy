import logging
import httpx
from datetime import date, datetime, timedelta, timezone as _tz
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select
from app.database import AsyncSessionLocal
from app.models.finance import Transaction
from app.models.journal import JournalEntry
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User
from app.models.workout import WorkoutLog, WorkoutPlan

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

MORNING_HOUR = 8   # 8 AM in the user's local timezone
EVENING_HOUR = 21  # 9 PM in the user's local timezone

MOOD_DISPLAY = {
    "great": "😊 Great",
    "good": "🙂 Good",
    "neutral": "😐 Neutral",
    "low": "😞 Low",
    "stressed": "😤 Stressed",
}


def _local_now(tz_str: str | None) -> datetime:
    """Return current time in the user's local timezone. Falls back to UTC."""
    now_utc = datetime.now(_tz.utc)
    try:
        return now_utc.astimezone(ZoneInfo(tz_str or "UTC"))
    except (ZoneInfoNotFoundError, Exception):
        return now_utc


async def _send_telegram(telegram_id: int, text: str, reply_markup: dict | None = None):
    from app.config import settings
    payload: dict = {"chat_id": telegram_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload,
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
    For each approved user, send their morning workout summary at exactly
    MORNING_HOUR:00 in their local timezone.
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
                if local_now.hour != MORNING_HOUR or local_now.minute != 0:
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


async def send_evening_checkin():
    """
    At EVENING_HOUR:00 in each user's local timezone, send a daily summary
    (tasks, workout, finance) and a mood prompt if not yet checked in.
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
                if local_now.hour != EVENING_HOUR or local_now.minute != 0:
                    continue

                local_today = local_now.date()

                # ── Tasks ─────────────────────────────────────────────────────
                active_tasks = (await db.execute(
                    select(Task).where(
                        Task.user_id == user.id,
                        Task.status.in_(["todo", "in_progress"]),
                    )
                )).scalars().all()

                # Convert the user's local day to a UTC window so updated_at
                # (stored in UTC) is compared correctly for non-UTC users.
                day_start_utc = (
                    datetime.combine(local_today, datetime.min.time())
                    .replace(tzinfo=local_now.tzinfo)
                    .astimezone(_tz.utc)
                    .replace(tzinfo=None)
                )
                day_end_utc = day_start_utc + timedelta(days=1)

                done_today = (await db.execute(
                    select(func.count(Task.id)).where(
                        Task.user_id == user.id,
                        Task.status == "done",
                        Task.updated_at >= day_start_utc,
                        Task.updated_at < day_end_utc,
                    )
                )).scalar() or 0

                # ── Workout ───────────────────────────────────────────────────
                workout_log = (await db.execute(
                    select(WorkoutLog).where(
                        WorkoutLog.user_id == user.id,
                        WorkoutLog.log_date == local_today,
                    ).order_by(WorkoutLog.created_at.desc()).limit(1)
                )).scalars().first()

                # ── Finance ───────────────────────────────────────────────────
                transactions = (await db.execute(
                    select(Transaction).where(
                        Transaction.user_id == user.id,
                        Transaction.transaction_date == local_today,
                    )
                )).scalars().all()

                # ── Mood ──────────────────────────────────────────────────────
                mood_entry = (await db.execute(
                    select(JournalEntry).where(
                        JournalEntry.user_id == user.id,
                        JournalEntry.entry_date == local_today,
                        JournalEntry.mood.isnot(None),
                    ).order_by(JournalEntry.created_at.desc()).limit(1)
                )).scalars().first()

                # ── Build message ─────────────────────────────────────────────
                today_str = local_today.strftime("%a %d %b")
                lines = [f"🌙 *Daily Wrap-Up — {today_str}*\n"]

                # Tasks row: only if there are active or done-today tasks
                if active_tasks or done_today:
                    parts = []
                    if done_today:
                        parts.append(f"{done_today} done")
                    ip = sum(1 for t in active_tasks if t.status == "in_progress")
                    td = sum(1 for t in active_tasks if t.status == "todo")
                    overdue = sum(
                        1 for t in active_tasks
                        if t.due_date and t.due_date.date() < local_today
                    )
                    if ip:
                        parts.append(f"{ip} in progress")
                    if td:
                        parts.append(f"{td} to do")
                    if overdue:
                        parts.append(f"{overdue} overdue ⚠️")
                    lines.append(f"📋 Tasks: {' · '.join(parts)}")

                # Workout row: always show
                if workout_log:
                    cat = (workout_log.category or "workout").replace("_", " ").title()
                    w_parts = [cat]
                    if workout_log.duration_min:
                        w_parts.append(f"{workout_log.duration_min}min")
                    if workout_log.calories_burnt:
                        w_parts.append(f"{workout_log.calories_burnt} kcal")
                    lines.append(f"💪 Workout: {' · '.join(w_parts)}")
                else:
                    lines.append("💪 Workout: rest day")

                # Finance row: only if there are transactions today
                if transactions:
                    currency = transactions[0].currency
                    spent = sum(t.amount for t in transactions if t.transaction_type == "expense")
                    earned = sum(t.amount for t in transactions if t.transaction_type == "income")
                    f_parts = []
                    if spent:
                        f_parts.append(f"Spent {currency} {spent:.0f}")
                    if earned:
                        f_parts.append(f"Earned {currency} {earned:.0f}")
                    f_parts.append(f"{len(transactions)} transaction(s)")
                    lines.append(f"💰 Finance: {' · '.join(f_parts)}")

                # Mood section
                if mood_entry:
                    lines.append(f"\nMood today: {MOOD_DISPLAY.get(mood_entry.mood, mood_entry.mood)}")
                    await _send_telegram(user.telegram_id, "\n".join(lines))
                else:
                    lines.append("\nHow's your day been?")
                    keyboard = {"inline_keyboard": [[
                        {"text": "😊 Great",    "callback_data": "mood_checkin:great"},
                        {"text": "🙂 Good",     "callback_data": "mood_checkin:good"},
                        {"text": "😐 Neutral",  "callback_data": "mood_checkin:neutral"},
                        {"text": "😞 Low",      "callback_data": "mood_checkin:low"},
                        {"text": "😤 Stressed", "callback_data": "mood_checkin:stressed"},
                    ]]}
                    await _send_telegram(user.telegram_id, "\n".join(lines), reply_markup=keyboard)

                log.info("[evening checkin] sent to user %d (tz=%s)", user.id, user.timezone)

            except Exception as exc:
                log.error("[evening checkin] failed for user %d: %s", user.id, exc)


def start_scheduler():
    common = {
        "trigger": "interval",
        "minutes": 1,
        "replace_existing": True,
        "coalesce": True,
        "max_instances": 1,
    }
    scheduler.add_job(
        check_and_send_reminders,
        id="reminders",
        misfire_grace_time=30,
        **common,
    )
    scheduler.add_job(
        send_workout_reminders,
        id="workout_reminders",
        misfire_grace_time=60,
        **common,
    )
    scheduler.add_job(
        send_evening_checkin,
        id="evening_checkin",
        misfire_grace_time=60,
        **common,
    )
    scheduler.start()
    log.info(
        "[scheduler] started — checks every minute; workout at %02d:00 and check-in at %02d:00 local per user",
        MORNING_HOUR, EVENING_HOUR,
    )


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
    log.info("[scheduler] stopped")
