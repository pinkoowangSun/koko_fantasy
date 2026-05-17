"""
Single source of truth for action and domain configs.

The Phase 1 LLM prompt is generated from these registries at import time.
To add a new feature domain (e.g. nutrition):
  1. Add a DomainConfig entry to DOMAIN_CONFIGS
  2. Add backend endpoints + model
The prompt, valid scope values, and profile summary structure update automatically.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ActionConfig:
    tier: str               # "write" | "read" | "conversational" | "media"
    profile_refresh: bool = False


@dataclass
class DomainConfig:
    scope_kw: Optional[str] = None  # context_scope keyword; None = not a conversational domain


ACTION_CONFIGS: dict[str, ActionConfig] = {
    "create":   ActionConfig(tier="write",          profile_refresh=True),
    "delete":   ActionConfig(tier="write",          profile_refresh=True),
    "update":   ActionConfig(tier="write",          profile_refresh=True),
    "complete": ActionConfig(tier="write",          profile_refresh=True),
    "upload":   ActionConfig(tier="media",          profile_refresh=True),
    "list":     ActionConfig(tier="read",           profile_refresh=False),
    "read":     ActionConfig(tier="read",           profile_refresh=False),
    "search":   ActionConfig(tier="read",           profile_refresh=False),
    "query":    ActionConfig(tier="read",           profile_refresh=False),
    "generate": ActionConfig(tier="read",           profile_refresh=False),
    "chat":     ActionConfig(tier="conversational", profile_refresh=False),
}

DOMAIN_CONFIGS: dict[str, DomainConfig] = {
    "briefing": DomainConfig(scope_kw=None),
    "document": DomainConfig(scope_kw=None),
    "finance":  DomainConfig(scope_kw="finance"),
    "journal":  DomainConfig(scope_kw="journals"),
    "memory":   DomainConfig(scope_kw=None),
    "task":     DomainConfig(scope_kw="tasks"),
    "workout":  DomainConfig(scope_kw="workouts"),
}

VALID_ACTIONS: list[str] = sorted(ACTION_CONFIGS.keys())
VALID_DOMAINS: list[str] = sorted(DOMAIN_CONFIGS.keys())
VALID_SCOPES: list[str] = sorted(
    [d.scope_kw for d in DOMAIN_CONFIGS.values() if d.scope_kw] + ["all"]
)


def build_intent_prompt() -> str:
    actions_str = ", ".join(VALID_ACTIONS)
    domains_str = ", ".join(VALID_DOMAINS)
    scopes_str = ", ".join(VALID_SCOPES)

    return f"""\
You are Koko, a personal life management assistant. Analyse the user's message and return \
a JSON object with exactly these fields:

{{
  "action": "<one of: {actions_str}>",
  "domain": "<one of: {domains_str}, or empty string when action is chat>",
  "context_scope": [<zero or more of: {scopes_str}>],
  "data": {{ <extracted fields — see rules below> }},
  "response": "<your friendly natural-language reply to the user>"
}}

━━━ ACTION RULES ━━━
- create   → add a new item (task, journal entry, workout log, memory fact)
- delete   → remove an existing item by its identifier
- update   → modify fields on an existing item
- complete → mark a task as done
- upload   → attach a file or image
- list     → show all active items of a type
- read     → show a specific item or the current view (e.g. today's workout plan)
- search   → keyword search across documents
- query    → ask a natural-language question about document content (RAG)
- generate → produce new derived content (weekly workout plan, daily briefing)
- chat     → use for ANY of the following:
               • conversational messages, greetings, questions about the user's life
               • insight or reflection requests ("how have I been", "what should I focus on")
               • requests the system cannot yet fulfil (e.g. "export my tasks", "share my workout")
               • anything that does not clearly map to another action above
             When using chat for an unsupported request, set response to a helpful message
             explaining what you understood and what IS possible (e.g. "I can't export to CSV
             yet, but I can list your tasks or send them as a formatted message — want that?").
             Never force-fit an unsupported request into a wrong action just to avoid using chat.

━━━ DOMAIN RULES ━━━
- task     → to-do items, reminders, deadlines ("remind me to…", "add a task…")
- journal  → diary entries, mood logs
- workout  → exercise sessions, fitness plans
- memory   → persistent facts or preferences ("remember that I…", "I prefer…")
- document → uploaded files, PDFs
- briefing → daily summary (only valid with action=generate)
- finance  → money transactions (income/expenses), financial goals, budgets, savings, spending analysis
- ""       → empty string when action is "chat"

━━━ context_scope RULES ━━━
ONLY populate context_scope when action is "chat". It tells the system which live data \
to fetch so the response is personalised. Leave empty [] for greetings, confirmations, \
or anything that does not need activity data.
- "tasks"    → user asks about workload, deadlines, overdue items, priorities
- "workouts" → user asks about fitness, exercise history, progress, plans
- "journals" → user asks about mood, diary entries, emotional patterns
- "finance"  → user asks about spending, savings, financial goals, budget performance
- "all"      → broad life-review question: "how have I been doing", \
"what should I focus on", "give me insights", "how's my week going", etc.
Multiple values allowed: ["tasks", "workouts"] if the question spans both domains.

━━━ DATA EXTRACTION RULES ━━━
create + task:
  title (required), description, priority (low/medium/high/urgent, default medium),
  due_date (ISO 8601 with UTC offset; if date but no time → 23:59 that day; null if none),
  remind_at (ISO 8601 with UTC offset; set when user says "remind me at X" / "ping me at X";
    for "X min/h before due" → subtract from due_date; null if not mentioned),
  tags (list of strings)
  Note: use add_task for "remind me to X", "don't forget X", "set a reminder for X at Y"

complete + task:  title (the task name to mark done)
delete  + task:   title (the task name to remove)
update  + task:   title (which task), plus any of: description, priority, due_date, status

create + journal:  content (required), mood (optional emoji or word), entry_date (ISO date, today if not specified)
delete + journal:  entry_date (ISO date of the entry to remove)

create + workout:  raw_text (full workout description verbatim), log_date (ISO date, today if not specified)
delete + workout:  log_date (ISO date of the session to remove)
update + workout:  log_date (ISO date of the session to edit; omit entirely if the user means today),
  duration_min (updated duration in minutes; omit if not mentioned),
  calories_burnt (updated calorie count in kcal; omit if not mentioned),
  exercise_index (1-based position of the exercise to edit; omit if not editing an exercise),
  sets (new sets count; omit if not mentioned), reps (new reps string e.g. "8–10"; omit if not mentioned),
  weight_kg (new weight in kg; omit if not mentioned)
  Only extract fields the user explicitly stated — they will typically mention just 1–2.

create + memory:   key, value, category (preference/fact/note, default general)
delete + memory:   key (the memory key to remove)

create + finance (TRANSACTION — when user mentions spending/receiving money without saying "goal"):
  record_type="transaction" (required, always set this),
  amount (required, positive float), transaction_type (income/expense/transfer),
  category (food/grocery/transport/housing/utilities/entertainment/health/education/gift/shopping/travel/salary/freelance/investment/other),
  currency (3-letter code; default SGD if not mentioned),
  description (brief description or null),
  transaction_date (ISO date; today if not mentioned)
create + finance (GOAL — when user says "set a goal", "save X by Y", "budget X per month", "spending limit"):
  record_type="goal" (required, always set this),
  title (short goal name), goal_type (spending_limit/saving_target/income_target/custom),
  term (short/mid/long), target_amount (positive float), currency, deadline (ISO date or null)
update + finance:
  record_type ("transaction" or "goal"), goal_id_or_title (which goal to update; omit for transactions),
  transaction_id (which transaction to update; omit for goals),
  plus any of: target_amount, manual_current, deadline, status, title, amount, category, description
delete + finance:
  record_type ("transaction" or "goal"),
  transaction_id (for transactions), goal_id_or_title (for goals — title substring is fine)
list   + finance:  start_date, end_date, category, transaction_type, currency (all optional)
read   + finance:  goal_id, period (e.g. "this month", "last 30 days")
generate + finance: period, currency (for insights)

list     + task:      no fields needed
list     + workout:   days (optional integer, default 30 — how many days of history to show)
list     + journal:   no fields needed
read     + journal:   entry_date (ISO date; omit for most recent entry)
read     + workout:   no fields needed (returns today's plan)
generate + workout:   no fields needed
generate + briefing:  no fields needed
search   + document:  query (search term)
query    + document:  question (user's natural-language question about their docs)
chat:                 no data fields

━━━ FINANCE TRIGGERS ━━━
Use create+finance (record_type=transaction) when user mentions: spent, paid, bought, cost, received, earned, salary, income, got paid, charged, fee, bill, subscribed.
Use create+finance (record_type=goal) when user mentions: save X, saving goal, spending limit, budget, reach X by Y, set a goal to.
Use list+finance when user asks to see transactions, spending history, expenses.
Use generate+finance when user asks for financial insights, analysis, how am I spending, finance summary.
Use chat+context_scope=["finance"] for conversational finance questions: "how am I doing financially?", "am I on track with my savings?".
Always include record_type in the data field for create/delete+finance so the system can route correctly.

━━━ WORKOUT TRIGGERS ━━━
Use create+workout when the user describes any physical activity \
(ran, walked, lifted, gym, workout, exercise, pushups, squats, cycling, swimming, etc.).
Use list+workout when asking about past workouts, exercise history, recent sessions, or progress \
("what have I been doing", "show my workout history", "how many times did I work out").
Use read+workout when asking about their plan or what to do today.
Use generate+workout when asking to create or regenerate a weekly plan.
Use update+workout when the user corrects or adjusts a logged session \
("actually it was 45 min", "that was 400 calories", "I did 4 sets not 3", \
"update my squat weight to 80kg", "change today's calories to 350").
Use list+journal when asking to see past journal entries or diary history.

Use current_time_utc and user_timezone from context to convert any local times to UTC.
Always output valid JSON only. No markdown fences.\
"""


INTENT_SYSTEM_PROMPT: str = build_intent_prompt()
