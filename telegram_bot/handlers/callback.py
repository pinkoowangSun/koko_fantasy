"""Handle inline keyboard callbacks (approve/reject user)."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot.handlers.api import api

log = logging.getLogger(__name__)


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

    try:
        if action == "approve":
            await api("post", f"/users/{user_id}/approve", json={
                "actor_telegram_id": query.from_user.id,
            })
            await query.edit_message_text(f"✅ User #{user_id} approved.")
        elif action == "reject":
            await api("post", f"/users/{user_id}/reject", json={
                "actor_telegram_id": query.from_user.id,
            })
            await query.edit_message_text(f"❌ User #{user_id} rejected.")
    except Exception as exc:
        log.error("[callback] approval action=%s user=%s failed: %s", action, user_id, exc)
        try:
            await query.edit_message_text(f"⚠️ Action failed: {exc}\n\nPlease use the web admin panel.")
        except Exception:
            pass
