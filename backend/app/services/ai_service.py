import json
from datetime import datetime
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.chat_history import ChatHistory
from app.services.intent_registry import (
    INTENT_SYSTEM_PROMPT,
    VALID_ACTIONS,
    VALID_DOMAINS,
    VALID_SCOPES,
)

_client = AsyncOpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
)


# ── Phase 1 response model ────────────────────────────────────────────────────

class Phase1Response(BaseModel):
    action: str
    domain: str = ""
    context_scope: list[str] = []
    data: dict = {}
    response: str = ""

    @model_validator(mode="after")
    def _validate_enums(self) -> "Phase1Response":
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"unknown action: {self.action!r}")
        if self.domain and self.domain not in VALID_DOMAINS:
            self.domain = ""
        self.context_scope = [s for s in self.context_scope if s in VALID_SCOPES]
        return self


_FALLBACK = Phase1Response(
    action="chat",
    domain="",
    context_scope=[],
    data={},
    response="I'm not sure I understood that — could you rephrase?",
)

_RETRY_PROMPT = (
    "Your previous response was invalid. "
    "Return ONLY valid JSON matching this schema exactly:\n"
    '{{"action": one of {actions}, "domain": one of {domains} or "", '
    '"context_scope": list from {scopes}, "data": {{}}, "response": "string"}}'
)


# ── History helpers ───────────────────────────────────────────────────────────

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


async def _save_messages(user_id: int, user_msg: str, assistant_msg: str, source: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(ChatHistory(user_id=user_id, role="user", content=user_msg, source=source))
        db.add(ChatHistory(user_id=user_id, role="assistant", content=assistant_msg, source=source))
        await db.commit()


# ── Phase 1: classify intent ──────────────────────────────────────────────────

async def classify_intent(user_id: int, message: str, user_context: str = "") -> Phase1Response:
    """
    Phase 1 LLM call: classify action + domain + context_scope.
    Validates output with Pydantic; retries once on failure; falls back to safe default.
    """
    history = await _get_recent_history(user_id, limit=6)
    system = INTENT_SYSTEM_PROMPT
    if user_context:
        system += f"\n\nUser context: {user_context}"

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    raw = ""
    try:
        resp = await _client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        result = Phase1Response.model_validate(json.loads(raw))
        await _save_messages(user_id, message, result.response, "telegram")
        return result

    except (ValidationError, json.JSONDecodeError, ValueError):
        # Retry once: send back the bad output with the schema
        retry_hint = _RETRY_PROMPT.format(
            actions=VALID_ACTIONS, domains=VALID_DOMAINS, scopes=VALID_SCOPES
        )
        retry_messages = messages + [
            {"role": "assistant", "content": raw or ""},
            {"role": "user", "content": retry_hint},
        ]
        try:
            resp2 = await _client.chat.completions.create(
                model=settings.DEEPSEEK_MODEL,
                messages=retry_messages,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            raw2 = resp2.choices[0].message.content
            result = Phase1Response.model_validate(json.loads(raw2))
            await _save_messages(user_id, message, result.response, "telegram")
            return result
        except Exception:
            pass

    fallback = _FALLBACK.model_copy()
    await _save_messages(user_id, message, fallback.response, "telegram")
    return fallback


# ── Phase 2: contextual response ──────────────────────────────────────────────

_PHASE2_SYSTEM = (
    "You are Koko, a warm and insightful personal life management assistant. "
    "Use the user's data provided below to give a specific, personalised response. "
    "Reference actual data points — dates, task names, workout categories, moods. "
    "Be concise but thorough. Proactively flag patterns or areas worth attention."
)


async def generate_contextual_response(
    user_id: int,
    message: str,
    profile_summary: str,
    rich_context: str,
) -> str:
    """
    Phase 2 LLM call: generate a rich, data-aware conversational response.
    Falls back to a generic reply if the call fails.
    """
    history = await _get_recent_history(user_id, limit=10)

    context_block = ""
    if profile_summary:
        context_block += f"## User Profile Summary\n{profile_summary}\n\n"
    if rich_context:
        context_block += rich_context

    system = _PHASE2_SYSTEM
    if context_block:
        system += f"\n\n{context_block}"

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    try:
        resp = await _client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=messages,
            temperature=0.7,
        )
        reply = resp.choices[0].message.content
        await _save_messages(user_id, message, reply, "telegram")
        return reply
    except Exception as exc:
        print(f"[ai] Phase 2 failed for user {user_id}: {exc}")
        return "I'm having trouble pulling your data right now. Try again in a moment!"


# ── Web chat (unchanged) ──────────────────────────────────────────────────────

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


# ── Briefing (unchanged) ──────────────────────────────────────────────────────

async def generate_briefing(
    user_id: int, tasks_summary: str, journal_summary: str, reminders_summary: str
) -> str:
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


# ── Workout helpers (unchanged) ───────────────────────────────────────────────

async def parse_workout_log(user_id: int, text: str) -> dict:
    prompt = (
        'Analyse this workout description and return JSON with this exact structure:\n'
        '{\n'
        '  "category": "<cardio|upper_body|lower_body|core|flexibility|mixed|rest>",\n'
        '  "summary": "<concise 1-2 sentence summary>",\n'
        '  "duration_min": <integer total minutes or null>,\n'
        '  "exercises": [\n'
        '    {"exercise_name": "<name>", "sets": <int or null>, "reps": "<string or null>", "weight_kg": <float or null>, "notes": "<string or null>"}\n'
        '  ]\n'
        '}\n\n'
        f'Description: {text}\n\n'
        'Rules:\n'
        '- Extract every distinct exercise or activity mentioned\n'
        '- For cardio (running, cycling, swimming): one entry, use reps for distance/duration (e.g. "5km", "30 min"), notes for pace if given\n'
        '- sets/weight_kg: integer/float only when explicitly stated, otherwise null\n'
        '- duration_min: total session time in minutes when mentioned, else null\n'
        '- exercises: empty array [] if nothing specific is mentioned\n'
        '- Return valid JSON only.'
    )
    resp = await _client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "You are a fitness analyst. Classify, summarise, and extract structured data from workout descriptions."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError:
        return {"category": "mixed", "summary": text[:200], "duration_min": None, "exercises": []}


async def generate_workout_insights(logs_data: list) -> dict:
    if not logs_data:
        return {
            "summary": "No workout history yet. Start logging your workouts to get personalised insights!",
            "consistency": "No data available yet.",
            "strengths": [],
            "improvements": ["Log your first workout to get started"],
            "trends": [],
            "recommendations": ["Begin by logging your workouts — even a short walk counts!"],
        }

    logs_str = json.dumps(logs_data, indent=2)
    prompt = f"""\
You are an expert fitness coach and data analyst. Analyse the following workout history (last 8 weeks) and return structured insights.

WORKOUT HISTORY:
{logs_str}

Return ONLY this JSON (no markdown fences):
{{
  "summary": "<2-3 sentence overall observation about the user's fitness journey and progress>",
  "consistency": "<1 sentence about workout frequency and consistency patterns, including average sessions per week>",
  "strengths": ["<specific strength 1>", "<specific strength 2>", "<specific strength 3>"],
  "improvements": ["<specific area to improve 1>", "<specific area to improve 2>"],
  "trends": ["<observable trend 1 referencing actual data>", "<observable trend 2>"],
  "recommendations": ["<concrete actionable recommendation 1>", "<concrete actionable recommendation 2>", "<concrete actionable recommendation 3>"]
}}

Rules:
- Be specific — reference actual exercises, dates, or patterns from the data
- Strengths: things the user is doing well (exactly 3 items)
- Improvements: muscle groups neglected or habits to fix (2–3 items)
- Trends: patterns visible over time such as frequency changes, volume shifts, category patterns (2–3 items)
- Recommendations: concrete next-step actions the user can take this week (exactly 3 items)
"""
    resp = await _client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert fitness coach. Output valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError:
        return {
            "summary": "Unable to generate insights at this time. Please try again.",
            "consistency": "Analysis unavailable.",
            "strengths": [],
            "improvements": [],
            "trends": [],
            "recommendations": ["Please try again later"],
        }


async def generate_workout_plan(
    user_id: int,
    logs_context: str,
    user_memory: str = "",
    workout_preference: str = "",
) -> dict:
    today_name = datetime.now().strftime("%A")
    history_block = logs_context.strip() or "No workout history yet — design a well-rounded beginner-friendly starter plan."
    memory_block = user_memory.strip() or "No additional profile data."
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
    "monday":    {{"focus": "...", "warmup": "...", "exercises": [{{"name": "...", "sets": 0, "reps": "...", "weight": "...", "notes": "..."}}], "cooldown": "...", "duration_min": 0, "notes": "..."}},
    "tuesday":   {{"focus": "...", "warmup": "...", "exercises": [], "cooldown": "...", "duration_min": 0, "notes": "..."}},
    "wednesday": {{"focus": "...", "warmup": "...", "exercises": [], "cooldown": "...", "duration_min": 0, "notes": "..."}},
    "thursday":  {{"focus": "...", "warmup": "...", "exercises": [], "cooldown": "...", "duration_min": 0, "notes": "..."}},
    "friday":    {{"focus": "...", "warmup": "...", "exercises": [], "cooldown": "...", "duration_min": 0, "notes": "..."}},
    "saturday":  {{"focus": "...", "warmup": "...", "exercises": [], "cooldown": "...", "duration_min": 0, "notes": "..."}},
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
