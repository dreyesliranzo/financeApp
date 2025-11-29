from collections import defaultdict
from datetime import date
from typing import Dict, List, Tuple

from sqlalchemy import func

from finance_app import db
from finance_app.models import Transaction, Budget


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
    rows = (
        query.with_entities(Transaction.category, Transaction.type, func.sum(Transaction.amount))
        .group_by(Transaction.category, Transaction.type)
        .all()
    )
    totals = defaultdict(float)
    for category, t_type, total in rows:
        sign = -1 if t_type == "expense" else 1
        totals[category] += sign * (total or 0)
    return dict(totals)


def summarize_monthly_spend(user_id: int) -> List[Tuple[str, float]]:
    rows = (
        Transaction.query.filter_by(user_id=user_id)
        .with_entities(func.strftime("%Y-%m", Transaction.date), Transaction.type, func.sum(Transaction.amount))
        .group_by(func.strftime("%Y-%m", Transaction.date), Transaction.type)
        .order_by(func.strftime("%Y-%m", Transaction.date))
        .all()
    )
    monthly = defaultdict(float)
    for month, t_type, total in rows:
        sign = -1 if t_type == "expense" else 1
        monthly[month] += sign * (total or 0)
    return sorted(monthly.items())


def balance_over_time(user_id: int) -> List[Tuple[str, float]]:
    rows = (
        Transaction.query.filter_by(user_id=user_id)
        .with_entities(Transaction.date, Transaction.type, Transaction.amount)
        .order_by(Transaction.date)
        .all()
    )
    balance_points = []
    running_total = 0.0
    for t_date, t_type, amount in rows:
        sign = -1 if t_type == "expense" else 1
        running_total += sign * amount
        balance_points.append((t_date.isoformat(), running_total))
    return balance_points


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
            .with_entities(func.sum(Transaction.amount))
            .scalar()
            or 0
        )
        percent = min((spent / budget.amount) * 100 if budget.amount else 0, 999)
        progress.append({"budget": budget, "spent": spent, "percent": percent})
    return progress
