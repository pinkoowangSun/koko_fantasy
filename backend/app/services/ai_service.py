import json
from datetime import datetime
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
read_journal | query_doc | briefing | add_memory | search | log_workout | view_workout_plan | generate_workout_plan>",
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
- log_workout: extract raw_text (the full workout description verbatim), \
log_date (ISO date, today if not specified)
- view_workout_plan: no data fields needed (user wants to see today's or this week's plan)
- generate_workout_plan: no data fields needed (user wants AI to create a new weekly plan)
- chat / list_tasks / read_journal: no special extraction needed

Workout-related triggers — use log_workout when the user mentions any physical activity \
(ran, walked, lifted, gym, workout, exercise, pushups, squats, etc.). \
Use view_workout_plan when asking about their plan or today's exercise. \
Use generate_workout_plan when asking to create or regenerate a plan.

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


async def parse_workout_log(user_id: int, text: str) -> dict:
    """Classify and summarise a free-text workout description."""
    prompt = (
        f'Analyse this workout description and return JSON:\n'
        f'{{"category": "<cardio|upper_body|lower_body|core|flexibility|mixed|rest>", '
        f'"summary": "<concise 1-2 sentence summary of what was done>"}}\n\n'
        f'Description: {text}\n\nReturn valid JSON only.'
    )
    resp = await _client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "You are a fitness analyst. Classify and summarise workout descriptions."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError:
        return {"category": "mixed", "summary": text[:200]}


async def generate_workout_plan(user_id: int, logs_context: str, user_memory: str = "", workout_preference: str = "") -> dict:
    """Generate a detailed, adaptive weekly workout plan using DeepSeek."""
    today_name = datetime.now().strftime("%A")

    history_block = logs_context.strip() if logs_context.strip() else "No workout history yet — design a well-rounded beginner-friendly starter plan."
    memory_block = user_memory.strip() if user_memory.strip() else "No additional profile data."

    pref_block = (
        f"\n⭐ WORKOUT PREFERENCE (user-specified — treat this as the highest priority input):\n{workout_preference.strip()}"
        if workout_preference.strip() else ""
    )

    prompt = f"""\
You are an expert certified personal trainer. Today is {today_name}.
{pref_block}
USER WORKOUT HISTORY (last 4 weeks):
{history_block}

OTHER USER PROFILE DATA:
{memory_block}

Generate a personalised, detailed weekly workout plan starting from Monday. \
Adapt the intensity, volume, and exercise selection based on the history above. \
If the user has been skipping certain muscle groups, include them. \
If they trained heavily recently, schedule deload or recovery. \
For complete beginners, start conservative with full-body sessions.

Return ONLY this JSON (no markdown fences):
{{
  "plan": {{
    "monday":    {{"focus": "...", "warmup": "...", "exercises": [{{"name": "...", "sets": N, "reps": "...", "weight": "...", "notes": "..."}}], "cooldown": "...", "duration_min": N, "notes": "..."}},
    "tuesday":   {{"focus": "...", "warmup": "...", "exercises": [...], "cooldown": "...", "duration_min": N, "notes": "..."}},
    "wednesday": {{"focus": "...", "warmup": "...", "exercises": [...], "cooldown": "...", "duration_min": N, "notes": "..."}},
    "thursday":  {{"focus": "...", "warmup": "...", "exercises": [...], "cooldown": "...", "duration_min": N, "notes": "..."}},
    "friday":    {{"focus": "...", "warmup": "...", "exercises": [...], "cooldown": "...", "duration_min": N, "notes": "..."}},
    "saturday":  {{"focus": "...", "warmup": "...", "exercises": [...], "cooldown": "...", "duration_min": N, "notes": "..."}},
    "sunday":    {{"focus": "Rest / Active Recovery", "warmup": "", "exercises": [], "cooldown": "", "duration_min": 0, "notes": "..."}}
  }},
  "notes": "<overall rationale: split logic, key adaptations from history, progression tips>"
}}

Rules:
- 3–6 exercises per active day; rest days have empty exercises array
- Include 1–2 rest or active-recovery days
- Balance push / pull / legs across the week
- weight field: use descriptive strings like "bodyweight", "moderate", "65–75% 1RM", "light"
- reps field: use strings like "8–10", "12–15", "30 sec", "AMRAP"
- All 7 days must be present in the plan
"""

    resp = await _client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert personal trainer. Output valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError:
        return {"plan": {}, "notes": "Failed to generate plan — please try again."}
