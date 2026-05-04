from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    # AI
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_BOT_USERNAME: str = ""

    # Internal bot ↔ backend auth
    BOT_API_KEY: str

    # JWT
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 30

    # Paths
    DATA_DIR: Path = BASE_DIR / "data"
    DB_PATH: Path = BASE_DIR / "data" / "db" / "koko.db"
    DOCUMENTS_DIR: Path = BASE_DIR / "data" / "documents"
    VECTORS_DIR: Path = BASE_DIR / "data" / "vectors"

    # Server
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    BOT_API_BASE: str = "https://kokofantasy.online"

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# Ensure data directories exist
for d in [settings.DATA_DIR / "db", settings.DOCUMENTS_DIR, settings.VECTORS_DIR]:
    d.mkdir(parents=True, exist_ok=True)
