from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot.handlers.api import api


async def handle_spend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/spend <amount> [currency] [category] [description]
    Example: /spend 50 SGD food lunch with colleagues
    """
    user = update.effective_user
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Log an expense:\n\n"
            "`/spend <amount> [currency] [category] [description]`\n\n"
            "Example: `/spend 50 SGD food lunch`",
            parse_mode="Markdown",
        )
        return

    amount_str = args[0]
    try:
        amount = float(amount_str.replace(",", ""))
    except ValueError:
        await update.message.reply_text("First argument must be a number (amount). Example: `/spend 50 food lunch`", parse_mode="Markdown")
        return

    CURRENCIES = {"SGD", "USD", "EUR", "GBP", "JPY", "CNY", "MYR", "HKD", "AUD", "CAD", "THB", "IDR", "PHP", "VND", "KRW"}
    CATEGORIES = {"food", "grocery", "transport", "housing", "utilities", "entertainment", "health", "education", "gift", "shopping", "travel", "investment", "other"}

    currency = "SGD"
    category = "other"
    desc_parts = []

    remaining = args[1:]
    for i, arg in enumerate(remaining):
        if arg.upper() in CURRENCIES and i == 0:
            currency = arg.upper()
        elif arg.lower() in CATEGORIES and not desc_parts:
            category = arg.lower()
        else:
            desc_parts.append(arg)

    description = " ".join(desc_parts) if desc_parts else None

    await update.message.chat.send_action("typing")
    try:
        result = await api("post", "/finance/transaction", json={
            "telegram_id": user.id,
            "amount": amount,
            "transaction_type": "expense",
            "category": category,
            "currency": currency,
            "description": description,
        })
        await update.message.reply_text(result.get("response", "✅ Expense logged!"), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Couldn't log expense: {exc}")


async def handle_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/income <amount> [currency] [description]
    Example: /income 5000 SGD monthly salary
    """
    user = update.effective_user
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Log income:\n\n"
            "`/income <amount> [currency] [description]`\n\n"
            "Example: `/income 5000 SGD monthly salary`",
            parse_mode="Markdown",
        )
        return

    try:
        amount = float(args[0].replace(",", ""))
    except ValueError:
        await update.message.reply_text("First argument must be a number. Example: `/income 5000 SGD salary`", parse_mode="Markdown")
        return

    CURRENCIES = {"SGD", "USD", "EUR", "GBP", "JPY", "CNY", "MYR", "HKD", "AUD", "CAD", "THB", "IDR", "PHP", "VND", "KRW"}
    currency = "SGD"
    desc_parts = []
    for i, arg in enumerate(args[1:]):
        if arg.upper() in CURRENCIES and i == 0:
            currency = arg.upper()
        else:
            desc_parts.append(arg)
    description = " ".join(desc_parts) if desc_parts else None

    # Best-effort category from description
    category = "salary"
    if description:
        desc_lower = description.lower()
        if any(k in desc_lower for k in ["freelance", "freelancing", "consulting", "contract"]):
            category = "freelance"
        elif any(k in desc_lower for k in ["invest", "dividend", "return", "stock", "crypto"]):
            category = "investment"

    await update.message.chat.send_action("typing")
    try:
        result = await api("post", "/finance/transaction", json={
            "telegram_id": user.id,
            "amount": amount,
            "transaction_type": "income",
            "category": category,
            "currency": currency,
            "description": description,
        })
        await update.message.reply_text(result.get("response", "✅ Income logged!"), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Couldn't log income: {exc}")


async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/balance — show this month's financial summary + active goals."""
    user = update.effective_user
    await update.message.chat.send_action("typing")
    try:
        result = await api("get", f"/finance/summary?telegram_id={user.id}")
        await update.message.reply_text(result.get("message", "No data yet."), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Couldn't fetch balance: {exc}")


async def handle_finance_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/goals — show all active financial goals with progress."""
    user = update.effective_user
    await update.message.chat.send_action("typing")
    try:
        result = await api("get", f"/finance/goals?telegram_id={user.id}")
        await update.message.reply_text(result.get("message", "No active goals."), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Couldn't fetch goals: {exc}")


async def handle_addgoal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addgoal <title> | <type> | <amount> <currency> | <deadline YYYY-MM-DD>
    Example: /addgoal Save for house | saving_target | 100000 SGD | 2028-12-31
    """
    user = update.effective_user
    raw = " ".join(context.args or [])
    if not raw:
        await update.message.reply_text(
            "Create a financial goal:\n\n"
            "`/addgoal <title> | <type> | <amount> <currency> | <deadline>`\n\n"
            "Types: `saving_target`, `spending_limit`, `income_target`, `custom`\n"
            "Example:\n`/addgoal Save for house | saving_target | 100000 SGD | 2028-12-31`\n\n"
            "Or just describe it in plain text — Koko will understand!",
            parse_mode="Markdown",
        )
        return

    parts = [p.strip() for p in raw.split("|")]
    title = parts[0] if len(parts) > 0 else raw
    goal_type = parts[1] if len(parts) > 1 else "saving_target"
    amount_currency = parts[2].split() if len(parts) > 2 else []
    deadline = parts[3] if len(parts) > 3 else None

    try:
        target_amount = float(amount_currency[0].replace(",", "")) if amount_currency else 0.0
    except (ValueError, IndexError):
        target_amount = 0.0

    currency = amount_currency[1].upper() if len(amount_currency) > 1 else "SGD"

    if not title or target_amount <= 0:
        await update.message.reply_text("Please provide a title and target amount. Example: `/addgoal Save for house | saving_target | 100000 SGD | 2028-12-31`", parse_mode="Markdown")
        return

    await update.message.chat.send_action("typing")
    try:
        result = await api("post", "/finance/goal", json={
            "telegram_id": user.id,
            "title": title,
            "goal_type": goal_type.strip(),
            "term": "long" if deadline else "mid",
            "target_amount": target_amount,
            "currency": currency,
            "deadline": deadline.strip() if deadline else None,
        })
        await update.message.reply_text(result.get("response", "✅ Goal created!"), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Couldn't create goal: {exc}")


async def handle_delgoal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/delgoal <goal_id or title>
    Example: /delgoal 3  or  /delgoal Save for house
    """
    user = update.effective_user
    identifier = " ".join(context.args or [])
    if not identifier:
        await update.message.reply_text(
            "Delete a goal:\n`/delgoal <id or title>`\n\nUse /goals to see your goals.",
            parse_mode="Markdown",
        )
        return
    await update.message.chat.send_action("typing")
    try:
        result = await api("delete", "/finance/goal", json={
            "telegram_id": user.id,
            "goal_id_or_title": identifier,
        })
        await update.message.reply_text(result.get("response", "✅ Goal deleted."), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Couldn't delete goal: {exc}")
