import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
BOT_API_BASE: str = os.environ.get("BOT_API_BASE", "https://kokofantasy.online")
BOT_API_KEY: str = os.environ["BOT_API_KEY"]
