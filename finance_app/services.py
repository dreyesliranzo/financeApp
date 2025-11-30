from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Tuple, Optional

from sqlalchemy import func

from finance_app import db
from finance_app.models import Transaction, Budget, Category, UserSettings, CurrencyRate


DEFAULT_CATEGORIES = [
    "Housing",
    "Transportation",
    "Food",
    "Utilities",
    "Entertainment",
    "Health",
    "Shopping",
    "Travel",
    "Savings",
    "Income",
    "Other",
]


def user_base_currency(user_id: int) -> str:
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    return settings.base_currency if settings else "USD"


def convert_to_base(user_id: int, amount: float, currency: Optional[str]) -> float:
    base = user_base_currency(user_id)
    if not currency or currency == base:
        return amount
    rate = CurrencyRate.query.filter_by(user_id=user_id, code=currency).first()
    if rate:
        return amount * rate.rate_to_base
    return amount  # fallback 1:1 if no rate set


def get_user_categories(user_id: int) -> List[str]:
    custom = Category.query.filter_by(user_id=user_id).all()
    names = [c.name for c in custom]
    # merge defaults + custom unique
    combined = []
    for name in DEFAULT_CATEGORIES + names:
        if name not in combined:
            combined.append(name)
    return combined


def get_transactions_for_period(user_id: int, start: date = None, end: date = None, category: str = None):
    query = Transaction.query.filter_by(user_id=user_id)
    if start:
        query = query.filter(Transaction.date >= start)
    if end:
        query = query.filter(Transaction.date <= end)
    if category:
        query = query.filter(Transaction.category == category)
    return query


def summarize_category_totals(user_id: int, start: date = None, end: date = None) -> Dict[str, float]:
    query = get_transactions_for_period(user_id, start, end)
    amount_expr = func.sum(Transaction.amount_base if Transaction.amount_base is not None else Transaction.amount)
    rows = query.with_entities(Transaction.category, Transaction.type, amount_expr).group_by(Transaction.category, Transaction.type).all()
    totals = defaultdict(float)
    for category, t_type, total in rows:
        sign = -1 if t_type == "expense" else 1
        totals[category] += sign * (total or 0)
    return dict(totals)


def summarize_monthly_spend(user_id: int) -> List[Tuple[str, float]]:
    """Aggregate by month (Postgres-friendly using date_trunc)."""
    month_expr = func.date_trunc("month", Transaction.date).label("month")
    rows = (
        Transaction.query.filter_by(user_id=user_id)
        .with_entities(month_expr, Transaction.type, func.sum(Transaction.amount_base if Transaction.amount_base is not None else Transaction.amount))
        .group_by(month_expr, Transaction.type)
        .order_by(month_expr)
        .all()
    )
    monthly = defaultdict(float)
    for month_dt, t_type, total in rows:
        month_label = month_dt.strftime("%Y-%m") if hasattr(month_dt, "strftime") else str(month_dt)
        sign = -1 if t_type == "expense" else 1
        monthly[month_label] += sign * (total or 0)
    return sorted(monthly.items())


def summarize_monthly_income_expense(user_id: int) -> List[Dict[str, object]]:
    """Return per-month income and expense totals."""
    month_expr = func.date_trunc("month", Transaction.date).label("month")
    rows = (
        Transaction.query.filter_by(user_id=user_id)
        .with_entities(month_expr, Transaction.type, func.sum(Transaction.amount_base if Transaction.amount_base is not None else Transaction.amount))
        .group_by(month_expr, Transaction.type)
        .order_by(month_expr)
        .all()
    )
    data = {}
    for month_dt, t_type, total in rows:
        key = month_dt.strftime("%Y-%m") if hasattr(month_dt, "strftime") else str(month_dt)
        if key not in data:
            data[key] = {"month": key, "income": 0.0, "expense": 0.0}
        if t_type == "income":
            data[key]["income"] = float(total or 0)
        else:
            data[key]["expense"] = float(total or 0)
    return [data[k] for k in sorted(data.keys())]


def balance_over_time(user_id: int) -> List[Tuple[str, float]]:
    rows = (
        Transaction.query.filter_by(user_id=user_id)
        .with_entities(
            Transaction.date,
            Transaction.type,
            Transaction.amount_base if Transaction.amount_base is not None else Transaction.amount,
        )
        .order_by(Transaction.date)
        .all()
    )
    balance_points = []
    running_total = 0.0
    for t_date, t_type, amount in rows:
        amount_val = amount or 0.0
        sign = -1 if t_type == "expense" else 1
        running_total += sign * amount_val
        balance_points.append((t_date.isoformat(), running_total))
    return balance_points


def forecast_balance(user_id: int, days: int = 30) -> List[Tuple[str, float]]:
    """Simple forecast: start from current balance, project daily average from last 90 days + recurring rules."""
    # current balance
    current = total_balance(user_id)
    today = date.today()
    start_window = today - timedelta(days=90)
    txs = get_transactions_for_period(user_id, start_window, today).all()
    if txs:
        daily_net = total_balance(user_id, start_window, today) / 90.0
    else:
        daily_net = 0.0

    # Add recurring rules impact
    from finance_app.models import RecurringRule

    rules = RecurringRule.query.filter_by(user_id=user_id).all()
    projections = []
    running = current
    for i in range(1, days + 1):
        day = today + timedelta(days=i)
        # apply daily average
        running += daily_net
        # add recurring rules that would hit on this day
        for rule in rules:
            # rough check by frequency
            delta = (day - rule.next_run).days
            if rule.frequency == "daily":
                hit = delta % 1 == 0 and delta >= 0
            elif rule.frequency == "weekly":
                hit = delta % 7 == 0 and delta >= 0
            else:
                hit = delta % 30 == 0 and delta >= 0
            if hit:
                sign = -1 if rule.type == "expense" else 1
                running += sign * convert_to_base(user_id, rule.amount, rule.currency)
        projections.append((day.isoformat(), running))
    return projections


def budget_progress(user_id: int, on_date: date = None):
    on_date = on_date or date.today()
    budgets = (
        Budget.query.filter_by(user_id=user_id)
        .filter(Budget.period_start <= on_date, Budget.period_end >= on_date)
        .all()
    )
    progress = []
    for budget in budgets:
        tx_query = get_transactions_for_period(user_id, budget.period_start, budget.period_end, budget.category)
        spent = (
            tx_query.filter(Transaction.type == "expense")
            .with_entities(func.sum(Transaction.amount_base if Transaction.amount_base is not None else Transaction.amount))
            .scalar()
            or 0
        )
        percent = min((spent / budget.amount) * 100 if budget.amount else 0, 999)
        progress.append({"budget": budget, "spent": spent, "percent": percent})
    return progress


def total_balance(user_id: int, start: date = None, end: date = None) -> float:
    """Income minus expenses for the given period."""
    tx_query = get_transactions_for_period(user_id, start, end)
    expenses = (
        tx_query.filter(Transaction.type == "expense")
        .with_entities(func.sum(Transaction.amount_base if Transaction.amount_base is not None else Transaction.amount))
        .scalar()
        or 0
    )
    income = (
        tx_query.filter(Transaction.type == "income")
        .with_entities(func.sum(Transaction.amount_base if Transaction.amount_base is not None else Transaction.amount))
        .scalar()
        or 0
    )
    return income - expenses
