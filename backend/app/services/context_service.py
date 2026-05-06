"""
Context building and profile summary services.

build_rich_context()      — fetches tiered live data per scope for Phase 2 LLM
refresh_profile_summary() — rebuilds the compact User.profile_summary from DB (no LLM)
"""
import asyncio
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.journal import JournalEntry
from app.models.memory import MemoryItem
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User
from app.models.workout import WorkoutLog


# ── Workout context (tiered temporal) ────────────────────────────────────────

async def _fetch_workout_context(user_id: int, db: AsyncSession) -> str:
    today = date.today()
    ninety_ago = today - timedelta(days=90)

    rows = (await db.execute(
        select(WorkoutLog)
        .where(WorkoutLog.user_id == user_id, WorkoutLog.log_date >= ninety_ago)
        .order_by(WorkoutLog.log_date.desc())
    )).scalars().all()

    if not rows:
        return "## Workouts\nNo workout history recorded yet."

    seven_ago = today - timedelta(days=7)
    fourteen_ago = today - timedelta(days=14)
    thirty_ago = today - timedelta(days=30)

    week_rows = [r for r in rows if r.log_date >= seven_ago]
    two_week_rows = [r for r in rows if r.log_date >= fourteen_ago]
    month_rows = [r for r in rows if r.log_date >= thirty_ago]

    sections: list[str] = []

    # 7-day full detail
    if week_rows:
        lines = ["## Workouts — Last 7 Days (full detail)"]
        for r in week_rows:
            lines.append(f"{r.log_date} [{r.category or 'unknown'}]: {r.raw_text[:200]}")
            if r.summary:
                lines.append(f"  → {r.summary}")
        sections.append("\n".join(lines))

    # 14-day aggregate
    if two_week_rows:
        cats = Counter(r.category or "unknown" for r in two_week_rows)
        cat_str = ", ".join(f"{c}×{n}" for c, n in cats.most_common())
        days_since = (today - two_week_rows[0].log_date).days
        sections.append(
            "## Workouts — Last 14 Days\n"
            f"{len(two_week_rows)} sessions: {cat_str}.\n"
            f"Days since last session: {days_since}."
        )

    # Monthly insights
    if month_rows:
        weekly_avg = len(month_rows) / 4.0
        cats = Counter(r.category or "unknown" for r in month_rows)
        most_freq = cats.most_common(1)[0]
        lines = [
            "## Workouts — Past Month Insights",
            f"{len(month_rows)} sessions ({weekly_avg:.1f}/week avg).",
            f"Most frequent: {most_freq[0]} ({most_freq[1]}×).",
        ]
        if len(cats) > 1:
            least_freq = cats.most_common()[-1]
            lines.append(
                f"Least frequent: {least_freq[0]} ({least_freq[1]}×) — consider adding more."
            )
        sections.append("\n".join(lines))

    # Quarterly trend (months beyond the 30-day window)
    quarter_rows = [r for r in rows if r.log_date < thirty_ago]
    if quarter_rows or month_rows:
        month_groups: dict[str, list] = defaultdict(list)
        for r in rows:
            month_groups[r.log_date.strftime("%b %Y")].append(r)

        if len(month_groups) > 1:
            lines = ["## Workouts — Past Quarter Trend"]
            for month_label in sorted(month_groups.keys()):
                m_rows = month_groups[month_label]
                dominant = Counter(r.category or "unknown" for r in m_rows).most_common(1)[0][0]
                lines.append(
                    f"{month_label}: {len(m_rows)} sessions "
                    f"({len(m_rows)/4.3:.1f}/wk avg). Focus: {dominant}."
                )
            sections.append("\n".join(lines))

    return "\n\n".join(sections)


# ── Task context ──────────────────────────────────────────────────────────────

async def _fetch_task_context(user_id: int, db: AsyncSession) -> str:
    now = datetime.utcnow()
    seven_ago = now - timedelta(days=7)
    thirty_ago = now - timedelta(days=30)

    active = (await db.execute(
        select(Task)
        .where(Task.user_id == user_id, Task.status.in_(["todo", "in_progress"]))
        .order_by(Task.due_date.asc().nullslast())
        .limit(20)
    )).scalars().all()

    recently_done = (await db.execute(
        select(Task)
        .where(Task.user_id == user_id, Task.status == "done",
               Task.updated_at >= seven_ago)
        .order_by(Task.updated_at.desc())
        .limit(5)
    )).scalars().all()

    done_30d = (await db.execute(
        select(func.count(Task.id))
        .where(Task.user_id == user_id, Task.status == "done",
               Task.updated_at >= thirty_ago)
    )).scalar() or 0

    sections: list[str] = []

    if active:
        overdue = [t for t in active if t.due_date and t.due_date < now]
        lines = [f"## Active Tasks ({len(active)})"]
        for t in active:
            due_str = ""
            if t.due_date:
                if t.due_date < now:
                    due_str = f" ⚠ OVERDUE since {t.due_date.strftime('%b %d')}"
                else:
                    due_str = f" — due {t.due_date.strftime('%b %d')}"
            lines.append(f"- [{t.priority}] {t.title}{due_str}")
        if overdue:
            lines.insert(1, f"⚠ {len(overdue)} task(s) overdue")
        sections.append("\n".join(lines))
    else:
        sections.append("## Active Tasks\nNo active tasks.")

    if recently_done:
        lines = ["## Completed This Week"]
        for t in recently_done:
            lines.append(f"- {t.title} (done {t.updated_at.strftime('%b %d')})")
        sections.append("\n".join(lines))

    sections.append(f"## Task Stats\nCompleted past 30 days: {done_30d}.")

    return "\n\n".join(sections)


# ── Journal context ───────────────────────────────────────────────────────────

async def _fetch_journal_context(user_id: int, db: AsyncSession) -> str:
    today = date.today()
    seven_ago = today - timedelta(days=7)
    thirty_ago = today - timedelta(days=30)

    recent = (await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id, JournalEntry.entry_date >= seven_ago)
        .order_by(JournalEntry.entry_date.desc())
    )).scalars().all()

    past_month = (await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id, JournalEntry.entry_date >= thirty_ago)
    )).scalars().all()

    sections: list[str] = []

    if recent:
        lines = [f"## Journal — Last 7 Days ({len(recent)} entries)"]
        for e in recent:
            mood_str = f" [{e.mood}]" if e.mood else ""
            content_preview = (e.content or "")[:150].replace("\n", " ")
            lines.append(f"{e.entry_date}{mood_str}: \"{content_preview}\"")
        sections.append("\n".join(lines))
    else:
        sections.append("## Journal — Last 7 Days\nNo entries this week.")

    if past_month:
        moods = [e.mood for e in past_month if e.mood]
        if moods:
            mood_counts = Counter(moods)
            mood_summary = ", ".join(f"{m}: {n}×" for m, n in mood_counts.most_common())
            sections.append(
                f"## Journal — Past 30 Days\n"
                f"{len(past_month)} entries. Mood distribution: {mood_summary}."
            )

    return "\n\n".join(sections)


# ── Reminder context ──────────────────────────────────────────────────────────

async def _fetch_reminder_context(user_id: int, db: AsyncSession) -> str:
    now = datetime.utcnow()
    seven_days = now + timedelta(days=7)

    upcoming = (await db.execute(
        select(Reminder)
        .where(
            Reminder.user_id == user_id,
            Reminder.sent.is_(False),
            Reminder.remind_at >= now,
            Reminder.remind_at <= seven_days,
        )
        .order_by(Reminder.remind_at.asc())
        .limit(10)
    )).scalars().all()

    if not upcoming:
        return "## Upcoming Reminders\nNone in the next 7 days."

    lines = [f"## Upcoming Reminders ({len(upcoming)})"]
    for r in upcoming:
        lines.append(f"- {r.remind_at.strftime('%b %d at %H:%M UTC')}: {r.message}")
    return "\n".join(lines)


# ── Public builder ────────────────────────────────────────────────────────────

async def build_rich_context(user_id: int, db: AsyncSession, scope: list[str]) -> str:
    """Fetch and format tiered live data for the given scope list."""
    fetch_all = "all" in scope
    tasks = []

    if fetch_all or "tasks" in scope:
        tasks.append(_fetch_task_context(user_id, db))
    if fetch_all or "workouts" in scope:
        tasks.append(_fetch_workout_context(user_id, db))
    if fetch_all or "journals" in scope:
        tasks.append(_fetch_journal_context(user_id, db))
    if fetch_all or "reminders" in scope:
        tasks.append(_fetch_reminder_context(user_id, db))

    if not tasks:
        return ""

    results = await asyncio.gather(*tasks)
    return "\n\n".join(r for r in results if r)


# ── Profile summary (template-based, no LLM) ─────────────────────────────────

async def _build_profile_summary(user_id: int, db: AsyncSession) -> str:
    today = date.today()
    now = datetime.utcnow()
    seven_ago_dt = now - timedelta(days=7)
    thirty_ago_d = today - timedelta(days=30)
    seven_ago_d = today - timedelta(days=7)

    # Tasks
    active_tasks = (await db.execute(
        select(Task)
        .where(Task.user_id == user_id, Task.status.in_(["todo", "in_progress"]))
        .order_by(Task.due_date.asc().nullslast())
        .limit(10)
    )).scalars().all()

    overdue = [t for t in active_tasks if t.due_date and t.due_date < now]
    next_due = next((t for t in active_tasks if t.due_date and t.due_date >= now), None)
    done_7d = (await db.execute(
        select(func.count(Task.id))
        .where(Task.user_id == user_id, Task.status == "done", Task.updated_at >= seven_ago_dt)
    )).scalar() or 0

    # Workouts
    workout_rows = (await db.execute(
        select(WorkoutLog)
        .where(WorkoutLog.user_id == user_id, WorkoutLog.log_date >= thirty_ago_d)
        .order_by(WorkoutLog.log_date.desc())
    )).scalars().all()

    week_workouts = [r for r in workout_rows if r.log_date >= seven_ago_d]

    # Journal
    journal_rows = (await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id, JournalEntry.entry_date >= seven_ago_d)
        .order_by(JournalEntry.entry_date.desc())
    )).scalars().all()

    # Memory
    memory_items = (await db.execute(
        select(MemoryItem)
        .where(MemoryItem.user_id == user_id)
        .limit(15)
    )).scalars().all()

    lines: list[str] = []

    # Tasks line
    task_parts = [f"{len(active_tasks)} active"]
    if overdue:
        overdue_titles = ", ".join(f'"{t.title}"' for t in overdue[:2])
        task_parts.append(f"{len(overdue)} overdue: {overdue_titles}")
    if next_due:
        task_parts.append(f'next due: "{next_due.title}" ({next_due.due_date.strftime("%b %d")})')
    task_parts.append(f"done this week: {done_7d}")
    lines.append("Tasks: " + "; ".join(task_parts) + ".")

    # Workouts line
    if workout_rows:
        weekly_avg = len(workout_rows) / 4.0
        cats_7d = [r.category or "unknown" for r in week_workouts]
        last = workout_rows[0]
        w_parts = [f"{len(week_workouts)} sessions past 7d"]
        if cats_7d:
            w_parts.append(f"({', '.join(cats_7d)})")
        w_parts.append(f"avg {weekly_avg:.1f}/wk past month")
        w_parts.append(f"last: {last.category or 'workout'} ({last.log_date})")
        lines.append("Workouts: " + "; ".join(w_parts) + ".")
    else:
        lines.append("Workouts: no sessions logged yet.")

    # Journal line
    if journal_rows:
        moods = [e.mood for e in journal_rows if e.mood]
        mood_str = ", ".join(moods[:4]) if moods else "no mood recorded"
        lines.append(
            f"Journal: {len(journal_rows)} entries past 7d. "
            f"Recent moods: {mood_str}. "
            f"Last entry: {journal_rows[0].entry_date}."
        )
    else:
        lines.append("Journal: no entries this week.")

    # Memory line
    if memory_items:
        mem_str = "; ".join(f"{m.key}: {m.value}" for m in memory_items[:8])
        lines.append(f"Memory: {mem_str}.")

    return "\n".join(lines)


async def refresh_profile_summary(user_id: int) -> None:
    """Rebuild and persist the profile summary. Runs as a background task."""
    async with AsyncSessionLocal() as db:
        try:
            summary = await _build_profile_summary(user_id, db)
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    profile_summary=summary,
                    profile_summary_updated_at=datetime.utcnow(),
                )
            )
            await db.commit()
        except Exception as exc:
            print(f"[context] profile refresh failed for user {user_id}: {exc}")
