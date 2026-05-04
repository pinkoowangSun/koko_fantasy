from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot.handlers.api import api


async def handle_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's workout plan."""
    user = update.effective_user
    await update.message.chat.send_action("typing")
    try:
        result = await api("get", f"/workout/today?telegram_id={user.id}")
        await update.message.reply_text(result.get("message", "No plan for today."), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Couldn't fetch workout plan: {exc}")


async def handle_logworkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log a workout from free text: /logworkout ran 5km + pushups"""
    user = update.effective_user
    text = " ".join(context.args) if context.args else ""

    if not text:
        await update.message.reply_text(
            "Tell me what you did!\n\n"
            "Example: `/logworkout ran 5km and did 3 sets of pushups`",
            parse_mode="Markdown",
        )
        return

    await update.message.chat.send_action("typing")
    try:
        result = await api("post", "/workout/log", json={
            "telegram_id": user.id,
            "raw_text": text,
        })
        cat = (result.get("category") or "workout").replace("_", " ").title()
        summary = result.get("summary", "")
        msg = f"✅ Workout logged! ({cat})"
        if summary:
            msg += f"\n_{summary}_"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Couldn't log workout: {exc}")


async def handle_genplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a new AI workout plan for this week."""
    user = update.effective_user
    await update.message.reply_text("🤖 Generating your personalised workout plan… this may take a moment.")
    await update.message.chat.send_action("typing")
    try:
        result = await api("post", "/workout/plan/generate", json={"telegram_id": user.id})
        notes = result.get("notes", "")
        msg = "💪 Your weekly workout plan is ready! Open the app to see the full schedule."
        if notes:
            msg += f"\n\n📋 _{notes}_"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Couldn't generate plan: {exc}")
