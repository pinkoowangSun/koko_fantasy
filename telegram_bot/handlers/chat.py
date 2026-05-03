from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot.handlers.api import api


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    intent = result.get("intent", "chat")
    data = result.get("data", {})
    response_text = result.get("response", "")

    if intent == "add_task":
        try:
            task = await api("post", "/tasks", json={
                "telegram_id": user.id,
                **{k: data[k] for k in ("title", "description", "priority", "due_date", "tags") if k in data},
            })
            await update.message.reply_text(
                f"✅ Task added: *{task['title']}*",
                parse_mode="Markdown",
            )
        except Exception:
            await update.message.reply_text(response_text or "Task created!")

    elif intent == "complete_task":
        title = data.get("title", text)
        try:
            result = await api("post", "/tasks/complete", json={"telegram_id": user.id, "title": title})
            if result.get("ok"):
                await update.message.reply_text(f"✅ Done: *{result['title']}*", parse_mode="Markdown")
            else:
                await update.message.reply_text("Couldn't find that task. Use /tasks to see your list.")
        except Exception:
            await update.message.reply_text(response_text or "Couldn't complete the task.")

    elif intent == "add_journal":
        try:
            await api("post", "/journal", json={
                "telegram_id": user.id,
                "content": data.get("content", text),
                "mood": data.get("mood"),
                "entry_date": data.get("entry_date"),
            })
            await update.message.reply_text("📓 Journal entry saved!")
        except Exception:
            await update.message.reply_text(response_text or "Entry saved!")

    elif intent == "briefing":
        try:
            briefing = await api("get", f"/briefing?telegram_id={user.id}")
            await update.message.reply_text(briefing.get("briefing", "No briefing available."))
        except Exception as exc:
            await update.message.reply_text(f"Couldn't fetch briefing: {exc}")

    elif intent == "query_doc":
        try:
            answer = await api("post", "/doc-qa", json={
                "telegram_id": user.id,
                "question": data.get("question", text),
            })
            await update.message.reply_text(answer.get("answer", "No answer found."))
        except Exception as exc:
            await update.message.reply_text(f"Document search failed: {exc}")

    elif intent == "add_memory":
        try:
            await api("post", "/memory", json={
                "telegram_id": user.id,
                "key": data.get("key", "note"),
                "value": data.get("value", text),
                "category": data.get("category", "general"),
            })
            await update.message.reply_text("🧠 Remembered!")
        except Exception:
            await update.message.reply_text(response_text or "Saved to memory!")

    else:
        await update.message.reply_text(response_text or "I'm not sure how to help with that.")
