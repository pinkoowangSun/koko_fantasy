from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot.handlers.api import api


async def handle_journal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    content = " ".join(context.args) if context.args else ""

    if not content:
        await update.message.reply_text(
            "Usage: /journal <your entry text>\n\nExample: /journal Had a productive day, finished the report."
        )
        return

    try:
        await api("post", "/journal", json={"telegram_id": user.id, "content": content})
        await update.message.reply_text("📓 Journal entry saved!")
    except Exception as exc:
        await update.message.reply_text(f"Failed to save: {exc}")
