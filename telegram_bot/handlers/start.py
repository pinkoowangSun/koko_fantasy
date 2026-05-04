from telegram import Update
from telegram.ext import ContextTypes


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! I'm *Koko*, your personal life assistant.\n\n"
        "*What I can do:*\n"
        "• Chat naturally — just talk to me\n"
        "• Add tasks — *\"add task: buy groceries tomorrow\"*\n"
        "• Mark done — /done <task title>\n"
        "• See tasks — /tasks\n"
        "• Daily briefing — /briefing\n"
        "• Journal — /journal <your entry>\n"
        "• Upload docs — send me any file\n"
        "• Ask about docs — *\"what does my report say about Q3?\"*\n"
        "• Search — /search <query>\n\n"
        "*Workout:*\n"
        "• Today's plan — /workout\n"
        "• Log workout — /logworkout <what you did>\n"
        "• Generate AI plan — /genplan\n"
        "• Or just type: *\"I just ran 5km\"*\n\n"
        "Just type anything to get started!",
        parse_mode="Markdown",
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Commands:*\n"
        "/start — introduction\n"
        "/briefing — today's daily summary\n"
        "/tasks — list active tasks\n"
        "/done <title> — mark a task complete\n"
        "/journal <text> — write a journal entry\n"
        "/search <query> — search across everything\n"
        "/workout — today's workout plan\n"
        "/logworkout <text> — log a workout session\n"
        "/genplan — generate AI weekly workout plan\n"
        "/help — this message",
        parse_mode="Markdown",
    )
