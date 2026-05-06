import io

from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot.handlers.api import api


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Photo message handler — routes to the MEDIA tier via POST /api/bot/media/{domain}.

    Domain is inferred from context (caption keywords or conversation state).
    Currently defaults to 'nutrition' for food photos; extend as more domains are added.
    """
    user = update.effective_user
    message = update.message
    caption = message.caption or ""

    await message.chat.send_action("upload_photo")

    # Infer domain from caption keywords (extend as new MEDIA domains are added)
    domain = _infer_media_domain(caption)

    # Download the highest-resolution photo
    photo = message.photo[-1]
    tg_file = await photo.get_file()
    buf = io.BytesIO()
    await tg_file.download_to_memory(buf)
    buf.seek(0)

    try:
        result = await api(
            "post",
            f"/media/{domain}",
            data={"telegram_id": str(user.id), "caption": caption},
            files={"file": (f"{domain}.jpg", buf, "image/jpeg")},
        )
    except Exception as exc:
        await message.reply_text(f"⚠️ Couldn't process the image: {exc}")
        return

    response = (result.get("response") or "").strip()
    await message.reply_text(
        response or "Image received! This feature is coming soon.",
        parse_mode="Markdown",
    )


def _infer_media_domain(caption: str) -> str:
    """Return the MEDIA domain keyword for a given caption. Defaults to 'nutrition'."""
    caption_lower = caption.lower()
    if any(kw in caption_lower for kw in ("food", "eat", "meal", "lunch", "dinner", "breakfast", "snack", "calorie")):
        return "nutrition"
    # Default: treat unrecognised photos as nutrition logs
    return "nutrition"
