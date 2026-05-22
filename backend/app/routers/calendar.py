from datetime import date, datetime, time as time_
from typing import List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from collections import defaultdict

from app.database import get_db
from app.models.document import Document
from app.models.finance import Transaction
from app.models.journal import JournalEntry
from app.models.task import Task
from app.models.user import User
from app.routers.auth import require_approved

router = APIRouter(prefix="/calendar", tags=["calendar"])

PRIORITY_COLOR = {
    "urgent": "#ef4444",
    "high": "#f97316",
    "medium": "#3b82f6",
    "low": "#6b7280",
}

MOOD_EMOJI = {
    "great": "😄",
    "good": "🙂",
    "neutral": "😐",
    "low": "😔",
    "stressed": "😤",
}


def _user_local_date(user: User) -> date:
    try:
        return datetime.now(ZoneInfo(user.timezone or "UTC")).date()
    except (ZoneInfoNotFoundError, Exception):
        return date.today()


def _day_range(d: date):
    """Return (start_datetime, end_datetime) covering the full calendar day."""
    return datetime.combine(d, time_.min), datetime.combine(d, time_(23, 59, 59, 999999))


@router.get("/events")
async def get_events(
    start: date = Query(...),
    end: date = Query(...),
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    start_dt = datetime.combine(start, time_.min)
    end_dt = datetime.combine(end, time_(23, 59, 59, 999999))
    events: List[dict] = []

    tasks = (await db.execute(
        select(Task).where(
            Task.user_id == uid,
            or_(
                and_(Task.due_date.is_not(None), Task.due_date >= start_dt, Task.due_date <= end_dt),
                and_(Task.due_date.is_(None), Task.created_at >= start_dt, Task.created_at <= end_dt),
            ),
        )
    )).scalars().all()
    for t in tasks:
        events.append({
            "id": f"task-{t.id}",
            "title": t.title,
            "start": (t.due_date.date() if t.due_date else t.created_at.date()).isoformat(),
            "backgroundColor": PRIORITY_COLOR.get(t.priority, "#3b82f6"),
            "borderColor": PRIORITY_COLOR.get(t.priority, "#3b82f6"),
            "extendedProps": {"type": "task", "ref_id": t.id, "status": t.status, "priority": t.priority},
        })

    journal = (await db.execute(
        select(JournalEntry).where(
            JournalEntry.user_id == uid,
            JournalEntry.entry_date >= start,
            JournalEntry.entry_date <= end,
        )
    )).scalars().all()
    for j in journal:
        mood_icon = MOOD_EMOJI.get(j.mood, "") if j.mood else ""
        base_title = j.title or "Journal"
        event_title = f"{mood_icon} {base_title}".strip() if mood_icon else f"📓 {base_title}"
        events.append({
            "id": f"journal-{j.id}",
            "title": event_title,
            "start": j.entry_date.isoformat(),
            "backgroundColor": "#10b981",
            "borderColor": "#10b981",
            "extendedProps": {"type": "journal", "ref_id": j.id, "mood": j.mood},
        })

    docs = (await db.execute(
        select(Document).where(
            Document.user_id == uid,
            Document.created_at >= start_dt,
            Document.created_at <= end_dt,
        )
    )).scalars().all()
    for d in docs:
        events.append({
            "id": f"doc-{d.id}",
            "title": f"📄 {d.original_name}",
            "start": d.created_at.date().isoformat(),
            "backgroundColor": "#f59e0b",
            "borderColor": "#f59e0b",
            "extendedProps": {"type": "document", "ref_id": d.id},
        })

    # Finance: one net-per-currency event per day
    fin_txs = (await db.execute(
        select(Transaction).where(
            Transaction.user_id == uid,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
    )).scalars().all()

    # Group by (date, currency) → net
    fin_by_day: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in fin_txs:
        sign = 1 if t.transaction_type == "income" else -1
        fin_by_day[t.transaction_date][t.currency] += sign * t.amount

    for day_date, by_currency in fin_by_day.items():
        parts = []
        for cur, net in sorted(by_currency.items()):
            parts.append(f"{'+'if net>=0 else ''}{net:,.0f} {cur}")
        label = " · ".join(parts)
        color = "#10b981" if all(v >= 0 for v in by_currency.values()) else "#ef4444"
        events.append({
            "id": f"finance-{day_date.isoformat()}",
            "title": f"💰 {label}",
            "start": day_date.isoformat(),
            "backgroundColor": color,
            "borderColor": color,
            "extendedProps": {"type": "finance"},
        })

    return events


@router.get("/day-detail")
async def get_day_detail(
    day: date = Query(...),
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    day_start, day_end = _day_range(day)

    tasks = (await db.execute(
        select(Task).where(
            Task.user_id == uid,
            or_(
                and_(Task.due_date >= day_start, Task.due_date <= day_end),
                and_(Task.due_date.is_(None), func.date(Task.created_at) == day.isoformat()),
            ),
        )
    )).scalars().all()

    journal = (await db.execute(
        select(JournalEntry).where(
            JournalEntry.user_id == uid,
            JournalEntry.entry_date == day,
        )
    )).scalars().all()

    docs = (await db.execute(
        select(Document).where(
            Document.user_id == uid,
            Document.created_at >= day_start,
            Document.created_at <= day_end,
        )
    )).scalars().all()

    finance_txs = (await db.execute(
        select(Transaction).where(
            Transaction.user_id == uid,
            Transaction.transaction_date == day,
        ).order_by(Transaction.created_at.desc())
    )).scalars().all()

    fin_income: dict[str, float] = defaultdict(float)
    fin_expense: dict[str, float] = defaultdict(float)
    for t in finance_txs:
        if t.transaction_type == "income":
            fin_income[t.currency] += t.amount
        elif t.transaction_type == "expense":
            fin_expense[t.currency] += t.amount

    return {
        "date": day.isoformat(),
        "tasks": [
            {"id": t.id, "title": t.title, "status": t.status, "priority": t.priority}
            for t in tasks
        ],
        "journal": [
            {
                "id": j.id,
                "title": j.title,
                "content": j.content,
                "content_html": j.content_html,
                "mood": j.mood,
                "mood_icon": MOOD_EMOJI.get(j.mood, "") if j.mood else "",
                "source": j.source,
            }
            for j in journal
        ],
        "documents": [
            {"id": d.id, "original_name": d.original_name, "source": d.source}
            for d in docs
        ],
        "finance": {
            "income_by_currency": {k: round(v, 2) for k, v in fin_income.items()},
            "expense_by_currency": {k: round(v, 2) for k, v in fin_expense.items()},
            "transactions": [
                {"id": t.id, "amount": t.amount, "transaction_type": t.transaction_type,
                 "category": t.category, "currency": t.currency, "description": t.description}
                for t in finance_txs
            ],
        },
    }


@router.get("/today")
async def get_today_summary(
    current_user: User = Depends(require_approved),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    today = _user_local_date(current_user)
    today_start, today_end = _day_range(today)

    tasks = (await db.execute(
        select(Task).where(
            Task.user_id == uid,
            Task.status.notin_(["done", "cancelled"]),
            or_(
                and_(Task.due_date >= today_start, Task.due_date <= today_end),
                and_(Task.due_date.is_(None), func.date(Task.created_at) == today.isoformat()),
            ),
        ).order_by(Task.created_at.desc())
    )).scalars().all()

    journal = (await db.execute(
        select(JournalEntry).where(
            JournalEntry.user_id == uid,
            JournalEntry.entry_date == today,
        ).order_by(JournalEntry.created_at.desc())
    )).scalars().all()

    finance_txs = (await db.execute(
        select(Transaction).where(
            Transaction.user_id == uid,
            Transaction.transaction_date == today,
        ).order_by(Transaction.created_at.desc())
    )).scalars().all()

    fin_income: dict[str, float] = defaultdict(float)
    fin_expense: dict[str, float] = defaultdict(float)
    for t in finance_txs:
        if t.transaction_type == "income":
            fin_income[t.currency] += t.amount
        elif t.transaction_type == "expense":
            fin_expense[t.currency] += t.amount

    return {
        "date": today.isoformat(),
        "tasks": [
            {"id": t.id, "title": t.title, "status": t.status, "priority": t.priority}
            for t in tasks
        ],
        "journal": [
            {
                "id": j.id,
                "title": j.title,
                "mood": j.mood,
                "mood_icon": MOOD_EMOJI.get(j.mood, "") if j.mood else "",
                "source": j.source,
            }
            for j in journal
        ],
        "finance": {
            "income_by_currency": {k: round(v, 2) for k, v in fin_income.items()},
            "expense_by_currency": {k: round(v, 2) for k, v in fin_expense.items()},
            "transactions": [
                {"id": t.id, "amount": t.amount, "transaction_type": t.transaction_type,
                 "category": t.category, "currency": t.currency, "description": t.description}
                for t in finance_txs
            ],
        },
    }


# ── IANA timezone → ISO 3166-1 alpha-2 country code ──────────────────────────
_TZ_COUNTRY: dict[str, str] = {
    # Asia
    "Asia/Singapore": "SG", "Asia/Shanghai": "CN", "Asia/Beijing": "CN",
    "Asia/Chongqing": "CN", "Asia/Harbin": "CN", "Asia/Kashgar": "CN",
    "Asia/Urumqi": "CN", "Asia/Hong_Kong": "HK", "Asia/Macau": "MO",
    "Asia/Tokyo": "JP", "Asia/Seoul": "KR", "Asia/Kolkata": "IN",
    "Asia/Calcutta": "IN", "Asia/Taipei": "TW", "Asia/Bangkok": "TH",
    "Asia/Jakarta": "ID", "Asia/Makassar": "ID", "Asia/Jayapura": "ID",
    "Asia/Manila": "PH", "Asia/Kuala_Lumpur": "MY", "Asia/Kuching": "MY",
    "Asia/Ho_Chi_Minh": "VN", "Asia/Saigon": "VN", "Asia/Hanoi": "VN",
    "Asia/Dubai": "AE", "Asia/Riyadh": "SA", "Asia/Karachi": "PK",
    "Asia/Dhaka": "BD", "Asia/Colombo": "LK", "Asia/Kathmandu": "NP",
    "Asia/Katmandu": "NP", "Asia/Kabul": "AF", "Asia/Tehran": "IR",
    "Asia/Baghdad": "IQ", "Asia/Jerusalem": "IL", "Asia/Beirut": "LB",
    "Asia/Amman": "JO", "Asia/Damascus": "SY", "Asia/Muscat": "OM",
    "Asia/Bahrain": "BH", "Asia/Qatar": "QA", "Asia/Kuwait": "KW",
    "Asia/Yerevan": "AM", "Asia/Tbilisi": "GE", "Asia/Baku": "AZ",
    "Asia/Tashkent": "UZ", "Asia/Almaty": "KZ", "Asia/Ulaanbaatar": "MN",
    "Asia/Rangoon": "MM", "Asia/Yangon": "MM", "Asia/Phnom_Penh": "KH",
    "Asia/Vientiane": "LA", "Asia/Brunei": "BN", "Asia/Dili": "TL",
    "Asia/Novosibirsk": "RU", "Asia/Vladivostok": "RU", "Asia/Yakutsk": "RU",
    "Asia/Irkutsk": "RU", "Asia/Krasnoyarsk": "RU", "Asia/Yekaterinburg": "RU",
    # Europe
    "Europe/London": "GB", "Europe/Dublin": "IE", "Europe/Berlin": "DE",
    "Europe/Paris": "FR", "Europe/Madrid": "ES", "Europe/Rome": "IT",
    "Europe/Amsterdam": "NL", "Europe/Brussels": "BE", "Europe/Zurich": "CH",
    "Europe/Vienna": "AT", "Europe/Stockholm": "SE", "Europe/Oslo": "NO",
    "Europe/Copenhagen": "DK", "Europe/Helsinki": "FI", "Europe/Warsaw": "PL",
    "Europe/Prague": "CZ", "Europe/Bratislava": "SK", "Europe/Budapest": "HU",
    "Europe/Bucharest": "RO", "Europe/Sofia": "BG", "Europe/Kiev": "UA",
    "Europe/Kyiv": "UA", "Europe/Moscow": "RU", "Europe/Samara": "RU",
    "Europe/Athens": "GR", "Europe/Istanbul": "TR", "Europe/Lisbon": "PT",
    "Europe/Riga": "LV", "Europe/Tallinn": "EE", "Europe/Vilnius": "LT",
    "Europe/Minsk": "BY", "Europe/Belgrade": "RS", "Europe/Zagreb": "HR",
    "Europe/Ljubljana": "SI", "Europe/Luxembourg": "LU", "Europe/Malta": "MT",
    "Europe/Reykjavik": "IS", "Atlantic/Reykjavik": "IS",
    # Americas
    "America/New_York": "US", "America/Chicago": "US", "America/Denver": "US",
    "America/Los_Angeles": "US", "America/Phoenix": "US", "America/Anchorage": "US",
    "America/Honolulu": "US", "America/Detroit": "US",
    "America/Indiana/Indianapolis": "US", "America/Kentucky/Louisville": "US",
    "America/Toronto": "CA", "America/Vancouver": "CA", "America/Montreal": "CA",
    "America/Winnipeg": "CA", "America/Edmonton": "CA", "America/Halifax": "CA",
    "America/St_Johns": "CA", "America/Sao_Paulo": "BR", "America/Manaus": "BR",
    "America/Fortaleza": "BR", "America/Recife": "BR", "America/Belem": "BR",
    "America/Mexico_City": "MX", "America/Monterrey": "MX", "America/Tijuana": "MX",
    "America/Buenos_Aires": "AR", "America/Argentina/Buenos_Aires": "AR",
    "America/Argentina/Cordoba": "AR", "America/Santiago": "CL",
    "America/Bogota": "CO", "America/Lima": "PE", "America/Caracas": "VE",
    "America/La_Paz": "BO", "America/Asuncion": "PY", "America/Montevideo": "UY",
    "America/Guayaquil": "EC", "America/Panama": "PA", "America/Costa_Rica": "CR",
    "America/Guatemala": "GT", "America/Santo_Domingo": "DO", "America/Havana": "CU",
    "America/Jamaica": "JM",
    # Oceania
    "Australia/Sydney": "AU", "Australia/Melbourne": "AU", "Australia/Brisbane": "AU",
    "Australia/Perth": "AU", "Australia/Adelaide": "AU", "Australia/Darwin": "AU",
    "Australia/Hobart": "AU", "Pacific/Auckland": "NZ", "Pacific/Fiji": "FJ",
    "Pacific/Honolulu": "US", "Pacific/Port_Moresby": "PG",
    # Africa
    "Africa/Cairo": "EG", "Africa/Johannesburg": "ZA", "Africa/Lagos": "NG",
    "Africa/Nairobi": "KE", "Africa/Casablanca": "MA", "Africa/Algiers": "DZ",
    "Africa/Tunis": "TN", "Africa/Tripoli": "LY", "Africa/Khartoum": "SD",
    "Africa/Addis_Ababa": "ET", "Africa/Dar_es_Salaam": "TZ",
    "Africa/Kampala": "UG", "Africa/Harare": "ZW", "Africa/Lusaka": "ZM",
    "Africa/Accra": "GH", "Africa/Abidjan": "CI", "Africa/Dakar": "SN",
    "Africa/Kinshasa": "CD", "Africa/Luanda": "AO", "Africa/Windhoek": "NA",
}


@router.get("/holidays")
async def get_holidays(
    start: date = Query(...),
    end: date = Query(...),
    current_user: User = Depends(require_approved),
):
    country_code = _TZ_COUNTRY.get(current_user.timezone or "UTC")
    if not country_code:
        return []

    years = set(range(start.year, end.year + 1))
    events: List[dict] = []

    async with httpx.AsyncClient(timeout=6.0) as client:
        for year in years:
            try:
                resp = await client.get(
                    f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country_code}",
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    continue
                for h in resp.json():
                    hdate = date.fromisoformat(h["date"])
                    if hdate < start or hdate > end:
                        continue
                    name = h.get("localName") or h.get("name", "Holiday")
                    events.append({
                        "id": f"holiday-{h['date']}-{country_code}",
                        "title": f"🎉 {name}",
                        "start": h["date"],
                        "allDay": True,
                        "classNames": ["fc-holiday-event"],
                        "extendedProps": {"type": "holiday", "globalName": h.get("name", "")},
                    })
            except Exception:
                continue

    return events
