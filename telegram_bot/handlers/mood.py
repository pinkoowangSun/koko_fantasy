from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot.handlers.api import api

MOOD_DISPLAY = {
    "great": "😊 Great",
    "good": "🙂 Good",
    "neutral": "😐 Neutral",
    "low": "😞 Low",
    "stressed": "😤 Stressed",
}


async def handle_mood_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mood_key = query.data.split(":", 1)[1]
    user = query.from_user

    try:
        await api("post", "/mood", json={"telegram_id": user.id, "mood": mood_key})
        label = MOOD_DISPLAY.get(mood_key, mood_key)

        original = query.message.text or ""
        lines = original.split("\n")
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                lines[i] = f"Mood today: {label}"
                break

        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
    except Exception:
        await query.answer("Couldn't save mood — please try again", show_alert=True)
