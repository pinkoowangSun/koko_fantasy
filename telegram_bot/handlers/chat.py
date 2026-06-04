from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram_bot.handlers.api import api


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Free-text message handler. The backend /intent endpoint is the full orchestrator:
    it runs Phase 1 (classify), executes write/read actions, and runs Phase 2 (contextual
    chat) when needed. This handler is intentionally thin — just relay and display.
    """
    user = update.effective_user
    text = (update.message.text or "").strip()

    # Intercept pending calorie correction
    log_id = context.user_data.pop("awaiting_calorie_log_id", None)
    if log_id is not None:
        try:
            calories = int(text)
            if calories <= 0:
                raise ValueError
        except ValueError:
            context.user_data["awaiting_calorie_log_id"] = log_id
            await update.message.reply_text("Please enter a positive number (e.g. `350`).", parse_mode="Markdown")
            return
        await update.message.chat.send_action("typing")
        try:
            await api("patch", f"/workout/{log_id}/calories", json={
                "telegram_id": user.id,
                "calories_burnt": calories,
            })
            await update.message.reply_text(f"✅ Calories updated to *{calories} kcal*.", parse_mode="Markdown")
        except Exception as exc:
            await update.message.reply_text(f"⚠️ Couldn't save calories: {exc}")
        return

    await update.message.chat.send_action("typing")

    try:
        result = await api("post", "/intent", json={
            "telegram_id": user.id,
            "username": user.username,
            "message": text,
            "language_code": user.language_code,
        })
    except Exception as exc:
        await update.message.reply_text(f"⚠️ Couldn't reach the server: {exc}")
        return

    response = (result.get("response") or "").strip()

    # If the AI created a workout log, offer calorie review
    data = result.get("data") or {}
    if result.get("action") == "create" and result.get("domain") == "workout":
        log_id = data.get("log_id")
        calories = data.get("calories_burnt")
        if log_id:
            if calories is not None:
                response += f"\n\n🔥 AI estimated *{calories} kcal* — correct?"
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✓ Looks right", callback_data=f"cal_ok:{log_id}"),
                    InlineKeyboardButton("✏️ Correct", callback_data=f"correct_cal:{log_id}"),
                ]])
            else:
                response += "\n\n🔥 Calories not estimated — add manually?"
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("Add calories", callback_data=f"correct_cal:{log_id}"),
                ]])
            await update.message.reply_text(
                response or "Workout logged!",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            return

    await update.message.reply_text(
        response or "I'm not sure how to help with that.",
        parse_mode="Markdown",
    )
