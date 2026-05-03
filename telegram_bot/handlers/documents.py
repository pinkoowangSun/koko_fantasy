from telegram import Update
from telegram.ext import ContextTypes
import httpx
from telegram_bot.config import BOT_API_BASE, BOT_API_KEY

ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
}


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tg_doc = update.message.document

    if not tg_doc:
        return

    mime = tg_doc.mime_type or ""
    if mime not in ALLOWED_MIME and not tg_doc.file_name.endswith((".pdf", ".docx", ".txt", ".md")):
        await update.message.reply_text(
            "Supported formats: PDF, DOCX, TXT, MD.\nSend one of those to store and search it."
        )
        return

    await update.message.reply_text("📥 Receiving file…")
    tg_file = await tg_doc.get_file()
    file_bytes = await tg_file.download_as_bytearray()

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{BOT_API_BASE}/api/bot/upload-doc",
                headers={"x-bot-key": BOT_API_KEY},
                data={"telegram_id": str(user.id)},
                files={"file": (tg_doc.file_name, bytes(file_bytes), mime or "application/octet-stream")},
            )
            resp.raise_for_status()
            result = resp.json()

        indexed = result.get("indexed", False)
        status = "✅ Indexed for Q&A" if indexed else "⚠️ Saved (indexing skipped — unsupported content)"
        await update.message.reply_text(
            f"📄 *{result['original_name']}* stored.\n{status}",
            parse_mode="Markdown",
        )
    except Exception as exc:
        await update.message.reply_text(f"Upload failed: {exc}")
