"""Handle inline keyboard callbacks (approve/reject user)."""
from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot.handlers.api import api


async def handle_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if ":" not in data:
        return

    action, user_id_str = data.split(":", 1)
    try:
        user_id = int(user_id_str)
    except ValueError:
        return

    if action == "approve":
        await api("post", f"/users/{user_id}/approve")
        await query.edit_message_text(f"✅ User #{user_id} approved.")
    elif action == "reject":
        await api("post", f"/users/{user_id}/reject")
        await query.edit_message_text(f"❌ User #{user_id} rejected.")
