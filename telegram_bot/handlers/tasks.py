from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot.handlers.api import api

PRIORITY_ICON = {"urgent": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
STATUS_ICON = {"in_progress": "🔄", "todo": "⏳"}


async def handle_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        result = await api("get", f"/tasks?telegram_id={user.id}")
        tasks = result.get("tasks", [])
    except Exception as exc:
        await update.message.reply_text(f"Failed to fetch tasks: {exc}")
        return

    if not tasks:
        await update.message.reply_text("🎉 No active tasks!")
        return

    lines = ["📋 *Your active tasks:*\n"]
    for t in tasks:
        icon = PRIORITY_ICON.get(t["priority"], "⚪")
        status = STATUS_ICON.get(t["status"], "⏳")
        due = f"  _(due {t['due_date'][:10]})_" if t.get("due_date") else ""
        lines.append(f"{status} {icon} {t['title']}{due}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    title = " ".join(context.args) if context.args else ""

    if not title:
        await update.message.reply_text("Usage: /done <task title>")
        return

    try:
        result = await api("post", "/tasks/complete", json={"telegram_id": user.id, "title": title})
        if result.get("ok"):
            await update.message.reply_text(f"✅ Completed: *{result['title']}*", parse_mode="Markdown")
        else:
            await update.message.reply_text("Task not found. Use /tasks to see your list.")
    except Exception as exc:
        await update.message.reply_text(f"Error: {exc}")
