import httpx
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.reminder import Reminder
from app.models.user import User

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


def start_scheduler():
    scheduler.add_job(check_and_send_reminders, "interval", minutes=1, id="reminders")
    scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
