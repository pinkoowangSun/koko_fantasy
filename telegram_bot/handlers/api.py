"""Shared helper for calling the backend API from the bot."""
import httpx
from telegram_bot.config import BOT_API_BASE, BOT_API_KEY

_HEADERS = {"x-bot-key": BOT_API_KEY}
_TIMEOUT = 30


async def api(method: str, path: str, **kwargs) -> dict:
    url = f"{BOT_API_BASE}/api/bot{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await getattr(client, method)(url, headers=_HEADERS, **kwargs)
        resp.raise_for_status()
        return resp.json()
