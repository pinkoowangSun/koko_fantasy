"""Telegram bot entry point."""
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from telegram_bot.config import TELEGRAM_BOT_TOKEN
from telegram_bot.handlers.briefing import handle_briefing
from telegram_bot.handlers.callback import handle_approval_callback
from telegram_bot.handlers.chat import handle_message
from telegram_bot.handlers.documents import handle_document
from telegram_bot.handlers.journal import handle_journal
from telegram_bot.handlers.search import handle_search
from telegram_bot.handlers.start import handle_help, handle_start
from telegram_bot.handlers.tasks import handle_done, handle_tasks
from telegram_bot.handlers.workout import handle_genplan, handle_logworkout, handle_workout


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("briefing", handle_briefing))
    app.add_handler(CommandHandler("tasks", handle_tasks))
    app.add_handler(CommandHandler("done", handle_done))
    app.add_handler(CommandHandler("journal", handle_journal))
    app.add_handler(CommandHandler("search", handle_search))
    app.add_handler(CommandHandler("workout", handle_workout))
    app.add_handler(CommandHandler("logworkout", handle_logworkout))
    app.add_handler(CommandHandler("genplan", handle_genplan))

    # Inline button callbacks (approve / reject user)
    app.add_handler(CallbackQueryHandler(handle_approval_callback, pattern=r"^(approve|reject):\d+$"))

    # File uploads
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Free-text → intent router (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
