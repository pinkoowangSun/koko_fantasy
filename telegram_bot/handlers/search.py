from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot.handlers.api import api


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    query = " ".join(context.args) if context.args else ""

    if not query:
        await update.message.reply_text("Usage: /search <query>")
        return

    # Search uses the public API — build a temporary JWT via the bot endpoint
    # For simplicity, the bot calls the generic search through an internal route
    try:
        # Reuse intent + direct search call workaround
        from telegram_bot.handlers.api import api as _api
        result = await _api("post", "/intent", json={
            "telegram_id": user.id,
            "username": user.username,
            "message": f"search for {query}",
        })
        await update.message.reply_text(result.get("response", "Search complete."))
    except Exception as exc:
        await update.message.reply_text(f"Search failed: {exc}")
