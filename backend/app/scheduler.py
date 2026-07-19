"""Standalone process for reminders and scheduled Telegram notifications."""
import asyncio
import logging
import signal

from app.database import init_db
from app.services.reminder_service import start_scheduler, stop_scheduler


async def run_scheduler_forever() -> None:
    await init_db()
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stopped.set)
        except NotImplementedError:
            pass

    start_scheduler()
    try:
        await stopped.wait()
    finally:
        stop_scheduler()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run_scheduler_forever())


if __name__ == "__main__":
    main()
