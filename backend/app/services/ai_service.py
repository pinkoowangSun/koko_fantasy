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
        '  "calories_burnt": <estimated integer kcal or null>,\n'
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
        '- calories_burnt: estimate kcal based on exercise type, duration, and intensity; assume 70kg body weight if unknown; cardio ~600 kcal/hr running / ~500 cycling / ~300 walking; strength ~300-500 kcal/hr; return null only if too vague\n'
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
        return {"category": "mixed", "summary": text[:200], "duration_min": None, "calories_burnt": None, "exercises": []}


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


# ── Finance helpers ───────────────────────────────────────────────────────────

async def parse_finance_transaction(user_id: int, text: str) -> dict:
    """
    Extract structured transaction data from free text.
    Returns dict with: amount, transaction_type, category, currency, description, transaction_date
    """
    from datetime import date as _date
    today = _date.today().isoformat()
    prompt = (
        f'Today is {today}. Extract a financial transaction from this text and return JSON:\n'
        '{{\n'
        '  "amount": <positive float>,\n'
        '  "transaction_type": "<income|expense|transfer>",\n'
        '  "category": "<food|grocery|transport|housing|utilities|entertainment|health|education|gift|shopping|travel|salary|freelance|investment|other>",\n'
        '  "currency": "<3-letter code, e.g. SGD, USD — default SGD if not mentioned>",\n'
        '  "description": "<brief description or null>",\n'
        '  "transaction_date": "<ISO date YYYY-MM-DD, today if not mentioned>",\n'
        '  "record_type": "transaction"\n'
        '}}\n\n'
        f'Text: {text}\n\n'
        'Rules:\n'
        '- "spent", "paid", "bought", "cost" → expense\n'
        '- "received", "earned", "salary", "income", "got paid" → income\n'
        '- amount is always positive\n'
        '- Return valid JSON only.'
    )
    resp = await _client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "You are a financial data extractor. Output valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError:
        return {
            "amount": 0.0, "transaction_type": "expense", "category": "other",
            "currency": "SGD", "description": text[:100], "transaction_date": today,
            "record_type": "transaction",
        }


async def parse_finance_goal(user_id: int, text: str) -> dict:
    """
    Extract a finance goal from free text.
    Returns dict with: title, goal_type, term, target_amount, currency, deadline, record_type
    """
    from datetime import date as _date
    today = _date.today().isoformat()
    prompt = (
        f'Today is {today}. Extract a financial goal from this text and return JSON:\n'
        '{{\n'
        '  "title": "<short goal title>",\n'
        '  "goal_type": "<spending_limit|saving_target|income_target|custom>",\n'
        '  "term": "<short|mid|long>",\n'
        '  "target_amount": <positive float>,\n'
        '  "currency": "<3-letter code, default SGD>",\n'
        '  "deadline": "<ISO date YYYY-MM-DD or null>",\n'
        '  "record_type": "goal"\n'
        '}}\n\n'
        f'Text: {text}\n\n'
        'Rules:\n'
        '- saving_target: "save X", "put aside X", "reach X savings"\n'
        '- spending_limit: "spend max X", "keep spending under X", "budget X"\n'
        '- term: short < 3 months, mid 3–12 months, long > 12 months\n'
        '- Return valid JSON only.'
    )
    resp = await _client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "You are a financial goal extractor. Output valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError:
        return {
            "title": text[:80], "goal_type": "saving_target", "term": "mid",
            "target_amount": 0.0, "currency": "SGD", "deadline": None, "record_type": "goal",
        }


async def generate_finance_insights(user_id: int, summary_data: dict) -> dict:
    """Generate LLM-powered finance insights from 30-day transaction data."""
    if not summary_data.get("transactions"):
        return {
            "summary": "No transactions recorded in the past 30 days. Start logging your income and expenses to get personalised insights!",
            "top_categories": [],
            "income_trend": "No data available.",
            "expense_trend": "No data available.",
            "goal_status_note": "Add financial goals to track your progress.",
            "advice": ["Log your first transaction to get started."],
        }

    data_str = json.dumps(summary_data, indent=2)
    prompt = f"""\
You are a personal finance advisor. Analyse the following 30-day financial data and return structured insights.

DATA:
{data_str}

Return ONLY this JSON (no markdown fences):
{{
  "summary": "<2-3 sentence overview of the user's financial health this month>",
  "top_categories": ["<top spending category 1>", "<top spending category 2>", "<top spending category 3>"],
  "income_trend": "<1 sentence about income pattern>",
  "expense_trend": "<1 sentence about spending pattern and any concerns>",
  "goal_status_note": "<1 sentence about goal progress, or encouragement if no goals>",
  "advice": ["<actionable advice 1>", "<actionable advice 2>", "<actionable advice 3>"]
}}

Rules:
- Be specific — reference actual amounts, categories, and patterns from the data
- advice: concrete next steps the user can take this week (exactly 3 items)
- Keep a positive but honest tone
"""
    resp = await _client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "You are a personal finance advisor. Output valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError:
        return {
            "summary": "Unable to generate insights at this time. Please try again.",
            "top_categories": [],
            "income_trend": "Analysis unavailable.",
            "expense_trend": "Analysis unavailable.",
            "goal_status_note": "Analysis unavailable.",
            "advice": ["Please try again later."],
        }


_WEEK_DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


async def generate_workout_plan(
    user_id: int,
    logs_context: str,
    user_memory: str = "",
    workout_preference: str = "",
    days_to_generate: list[str] | None = None,
) -> dict:
    today_name = datetime.now().strftime("%A")
    history_block = logs_context.strip() or "No workout history yet — design a well-rounded beginner-friendly starter plan."
    memory_block = user_memory.strip() or "No additional profile data."
    pref_block = (
        f"\n⭐ WORKOUT PREFERENCE (user-specified — treat this as the highest priority input):\n{workout_preference.strip()}"
        if workout_preference.strip() else ""
    )

    target_days = days_to_generate if days_to_generate else _WEEK_DAYS
    day_schema = (
        '{"focus": "...", "warmup": "...", "exercises": '
        '[{"name": "...", "sets": 0, "reps": "...", "weight": "...", "notes": "..."}], '
        '"cooldown": "...", "duration_min": 0, "notes": "..."}'
    )
    plan_entries = ",\n    ".join(f'"{d}": {day_schema}' for d in target_days)

    if days_to_generate:
        scope_line = (
            f"Generate a workout plan for ONLY these remaining days of the week: "
            f"{', '.join(days_to_generate)}. "
            "Past days are already fixed — do not include them."
        )
        days_rule = f"Only the requested days must appear in the plan: {', '.join(days_to_generate)}."
    else:
        scope_line = (
            "Generate a personalised, detailed weekly workout plan starting from Monday. "
            "Adapt the intensity, volume, and exercise selection based on the history above. "
            "If the user has been skipping certain muscle groups, include them. "
            "If they trained heavily recently, schedule deload or recovery. "
            "For complete beginners, start conservative with full-body sessions."
        )
        days_rule = "All 7 days must be present in the plan."

    prompt = f"""\
You are an expert certified personal trainer. Today is {today_name}.
{pref_block}
USER WORKOUT HISTORY (last 4 weeks):
{history_block}

OTHER USER PROFILE DATA:
{memory_block}

{scope_line}

Return ONLY this JSON (no markdown fences):
{{
  "plan": {{
    {plan_entries}
  }},
  "notes": "<overall rationale: split logic, key adaptations from history, progression tips>"
}}

Rules:
- 3–6 exercises per active day; rest days have empty exercises array
- Include 1–2 rest or active-recovery days where appropriate
- Balance push / pull / legs across the week
- weight field: use descriptive strings like "bodyweight", "moderate", "65–75% 1RM", "light"
- reps field: use strings like "8–10", "12–15", "30 sec", "AMRAP"
- {days_rule}
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
