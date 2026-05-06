from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot.handlers.api import api


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Free-text message handler. The backend /intent endpoint is the full orchestrator:
    it runs Phase 1 (classify), executes write/read actions, and runs Phase 2 (contextual
    chat) when needed. This handler is intentionally thin — just relay and display.
    """
    user = update.effective_user
    text = update.message.text or ""

    await update.message.chat.send_action("typing")

    try:
        result = await api("post", "/intent", json={
            "telegram_id": user.id,
            "username": user.username,
            "message": text,
        })
    except Exception as exc:
        await update.message.reply_text(f"⚠️ Couldn't reach the server: {exc}")
        return

    response = (result.get("response") or "").strip()
    await update.message.reply_text(
        response or "I'm not sure how to help with that.",
        parse_mode="Markdown",
    )
