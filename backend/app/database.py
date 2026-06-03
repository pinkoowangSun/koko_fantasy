from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


engine = create_async_engine(
    f"sqlite+aiosqlite:///{settings.DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    # Import all models so Base knows about them
    from app.models import user, task, journal, document, memory, reminder, chat_history, workout, finance, food_log  # noqa
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Column migrations for existing databases
        for sql in [
            "ALTER TABLE users ADD COLUMN status VARCHAR DEFAULT 'approved'",
            "ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0",
            "ALTER TABLE users ADD COLUMN notified_admin BOOLEAN DEFAULT 0",
            "ALTER TABLE users ADD COLUMN profile_summary TEXT",
            "ALTER TABLE users ADD COLUMN profile_summary_updated_at DATETIME",
            "ALTER TABLE workout_logs ADD COLUMN duration_min INTEGER",
            "ALTER TABLE workout_logs ADD COLUMN calories_burnt INTEGER",
            "ALTER TABLE workout_exercises ADD COLUMN source VARCHAR DEFAULT 'user'",
            "ALTER TABLE documents ADD COLUMN updated_at DATETIME",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_user_key ON memory_items (user_id, key)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_workout_plan_user_week ON workout_plans (user_id, week_start)",
            "ALTER TABLE finance_transactions ADD COLUMN asset_id INTEGER REFERENCES finance_assets(id)",
            "ALTER TABLE finance_transactions ADD COLUMN to_asset_id INTEGER REFERENCES finance_assets(id)",
        ]:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass  # column already exists
