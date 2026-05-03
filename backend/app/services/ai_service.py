import json
from openai import AsyncOpenAI
from sqlalchemy import select
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.chat_history import ChatHistory

_client = AsyncOpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
)

INTENT_SYSTEM_PROMPT = """\
You are Koko, a personal life management assistant. Analyze the user's message and return \
a JSON object with exactly these fields:

{
  "intent": "<one of: chat | add_task | list_tasks | complete_task | add_journal | \
read_journal | query_doc | briefing | add_memory | search>",
  "data": { <extracted fields depending on intent> },
  "response": "<your friendly natural-language reply to the user>"
}

Intent extraction rules:
- add_task: extract title (required), description, priority (low/medium/high/urgent, default medium), \
due_date (ISO 8601 if mentioned, else null), tags (list of strings)
- complete_task: extract title (the task name to mark done)
- add_journal: extract content (required), mood (optional emoji or word), \
entry_date (ISO date, today if not specified)
- query_doc: extract question (the user's question about their documents)
- briefing: no data fields needed
- search: extract query (the search term)
- add_memory: extract key, value, category (preference/fact/note, default general)
- chat / list_tasks / read_journal: no special extraction needed

Always output valid JSON only. No markdown fences.\
"""


async def _get_recent_history(user_id: int, limit: int = 10) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChatHistory)
            .where(ChatHistory.user_id == user_id)
            .order_by(ChatHistory.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [{"role": r.role, "content": r.content} for r in reversed(rows)]


async def _save_messages(user_id: int, user_msg: str, assistant_msg: str, source: str):
    async with AsyncSessionLocal() as db:
        db.add(ChatHistory(user_id=user_id, role="user", content=user_msg, source=source))
        db.add(ChatHistory(user_id=user_id, role="assistant", content=assistant_msg, source=source))
        await db.commit()


async def detect_intent(user_id: int, message: str, user_context: str = "") -> dict:
    history = await _get_recent_history(user_id, limit=6)
    system = INTENT_SYSTEM_PROMPT
    if user_context:
        system += f"\n\nUser context: {user_context}"

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    resp = await _client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=messages,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"intent": "chat", "data": {}, "response": raw}

    await _save_messages(user_id, message, result.get("response", ""), "telegram")
    return result


async def chat(user_id: int, message: str, user_context: str = "", source: str = "web") -> str:
    history = await _get_recent_history(user_id, limit=10)
    system = (
        "You are Koko, a friendly personal life management assistant. "
        "Be concise, warm, and helpful.\n"
        + (f"User context: {user_context}" if user_context else "")
    )

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    resp = await _client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=messages,
        temperature=0.7,
    )
    reply = resp.choices[0].message.content
    await _save_messages(user_id, message, reply, source)
    return reply


async def generate_briefing(user_id: int, tasks_summary: str, journal_summary: str, reminders_summary: str) -> str:
    prompt = (
        f"Generate a concise, friendly daily briefing.\n\n"
        f"Active tasks:\n{tasks_summary}\n\n"
        f"Journal today:\n{journal_summary}\n\n"
        f"Upcoming reminders:\n{reminders_summary}\n\n"
        "Keep it motivating and well-structured with clear sections."
    )
    resp = await _client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "You are Koko, a personal assistant. Generate daily briefings."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
    )
    return resp.choices[0].message.content
