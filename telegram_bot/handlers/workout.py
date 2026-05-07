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


async def handle_editworkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit a workout log.

    Usage:
      /editworkout                        — show today's log
      /editworkout date=YYYY-MM-DD        — show a specific date's log
      /editworkout duration=45 calories=350
      /editworkout ex=1 sets=3 reps=8 kg=60
      /editworkout date=2026-05-04 duration=50
    """
    user = update.effective_user
    args = context.args or []

    # Parse key=value pairs
    kwargs: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            k, _, v = arg.partition("=")
            kwargs[k.lower()] = v

    # No args → show the current log
    if not kwargs:
        await update.message.chat.send_action("typing")
        try:
            result = await api("get", f"/workout/log?telegram_id={user.id}")
            await update.message.reply_text(result.get("message", "No workout found."), parse_mode="Markdown")
        except Exception as exc:
            await update.message.reply_text(f"Couldn't fetch workout: {exc}")
        return

    # Build edit payload
    payload: dict = {"telegram_id": user.id}
    if "date" in kwargs:
        payload["log_date"] = kwargs["date"]
    if "duration" in kwargs:
        try:
            payload["duration_min"] = int(kwargs["duration"])
        except ValueError:
            pass
    if "calories" in kwargs:
        try:
            payload["calories_burnt"] = int(kwargs["calories"])
        except ValueError:
            pass
    if "ex" in kwargs:
        try:
            payload["exercise_index"] = int(kwargs["ex"])
        except ValueError:
            pass
    if "sets" in kwargs:
        try:
            payload["sets"] = int(kwargs["sets"])
        except ValueError:
            pass
    if "reps" in kwargs:
        payload["reps"] = kwargs["reps"]
    if "kg" in kwargs:
        try:
            payload["weight_kg"] = float(kwargs["kg"])
        except ValueError:
            pass

    await update.message.chat.send_action("typing")
    try:
        result = await api("patch", "/workout/edit", json=payload)
        await update.message.reply_text(result.get("message", "✅ Workout updated!"), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Couldn't edit workout: {exc}")
