from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot.handlers.api import api


async def handle_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.chat.send_action("typing")

    try:
        result = await api("get", f"/briefing?telegram_id={user.id}")
        await update.message.reply_text(result.get("briefing", "No briefing available."))
    except Exception as exc:
        await update.message.reply_text(f"Couldn't generate briefing: {exc}")
