from datetime import date, datetime, timedelta
import csv
import io
import json
import os

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    send_file,
    Response,
    send_from_directory,
)
from flask_login import login_required, current_user

from finance_app import db
from finance_app.models import (
    Transaction,
    Budget,
    SavingsGoal,
    Category,
    CurrencyRate,
    UserSettings,
    RecurringRule,
    Attachment,
    CategoryRule,
)
from finance_app.services import (
    DEFAULT_CATEGORIES,
    get_user_categories,
    get_transactions_for_period,
    summarize_category_totals,
    summarize_monthly_spend,
    balance_over_time,
    budget_progress,
    total_balance,
    convert_to_base,
    user_base_currency,
    summarize_monthly_income_expense,
    forecast_balance,
    weekly_net,
)
from finance_app.email_utils import send_email
from werkzeug.utils import secure_filename

main_bp = Blueprint("main", __name__)
BASE_CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD", "JPY", "MXN"]


def _parse_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _save_attachment(transaction_id: int):
    file = request.files.get("receipt")
    if not file or not file.filename:
        return
    from finance_app.config import Config

    filename = secure_filename(file.filename)
    upload_folder = Config.UPLOAD_FOLDER
    os.makedirs(upload_folder, exist_ok=True)
    path = os.path.join(upload_folder, filename)
    file.save(path)
    attach = Attachment(transaction_id=transaction_id, filename=filename, original_name=file.filename)
    db.session.add(attach)
    db.session.commit()


def _apply_category_rule(user_id: int, description: str, current_category: str) -> str:
    """Return category based on rules if description matches; otherwise existing category."""
    if not description:
        return current_category
    if current_category and current_category != "Other":
        return current_category
    desc_lower = description.lower()
    rules = CategoryRule.query.filter_by(user_id=user_id).all()
    best = None
    for rule in rules:
        if rule.keyword.lower() in desc_lower:
            # prefer longest keyword match
            if not best or len(rule.keyword) > len(best.keyword):
                best = rule
    return best.category if best else current_category


def _maybe_send_alerts(tx: Transaction, settings: UserSettings):
    if not settings:
        return
    # Large transaction alert
    if settings.alert_large and tx.amount >= settings.alert_large:
        subj = "Pulse alert: Large transaction"
        body = f"A {tx.type} of {tx.currency or ''}{tx.amount:.2f} in {tx.category} on {tx.date}"
        send_email(current_user.email, subj, body)


def _check_budget_alerts(tx: Transaction, settings: UserSettings):
    if not settings or not settings.alert_budget_pct:
        return
    budgets = (
        Budget.query.filter_by(user_id=tx.user_id)
        .filter(Budget.period_start <= tx.date, Budget.period_end >= tx.date)
        .all()
    )
    for budget in budgets:
        spent = (
            Transaction.query.filter_by(user_id=tx.user_id)
            .filter(Transaction.date >= budget.period_start, Transaction.date <= budget.period_end)
            .filter(Transaction.type == "expense")
            .filter(Transaction.category == budget.category if budget.category else True)
            .with_entities(
                db.func.sum(db.func.coalesce(Transaction.amount_base, Transaction.amount))
            )
            .scalar()
            or 0
        )
        percent = (spent / budget.amount) * 100 if budget.amount else 0
        if percent >= settings.alert_budget_pct:
            subj = "Pulse alert: Budget threshold reached"
            label = budget.category or "All categories"
            body = f"Budget '{label}' is at {percent:.1f}% (${spent:.2f} of ${budget.amount:.2f})."
            send_email(current_user.email, subj, body)


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


def _process_recurring(user_id: int):
    today = date.today()
    rules = RecurringRule.query.filter_by(user_id=user_id).all()
    for rule in rules:
        while rule.next_run and rule.next_run <= today:
            amount_base = convert_to_base(user_id, rule.amount, rule.currency)
            tx = Transaction(
                user_id=user_id,
                date=rule.next_run,
                type=rule.type,
                category=rule.category,
                amount=rule.amount,
                currency=rule.currency,
                amount_base=amount_base,
                description=rule.description or f"Recurring: {rule.name}",
            )
            db.session.add(tx)
            if rule.frequency == "daily":
                rule.next_run = rule.next_run + timedelta(days=1)
            elif rule.frequency == "weekly":
                rule.next_run = rule.next_run + timedelta(weeks=1)
            else:
                rule.next_run = rule.next_run + timedelta(days=30)
    db.session.commit()


@main_bp.route("/dashboard")
@login_required
def dashboard():
    _process_recurring(current_user.id)
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    start = _parse_date(start_str)
    end = _parse_date(end_str)

    amount_expr = db.func.coalesce(Transaction.amount_base, Transaction.amount)
    tx_query = get_transactions_for_period(current_user.id, start, end)
    expenses = tx_query.filter(Transaction.type == "expense").with_entities(db.func.sum(amount_expr)).scalar() or 0
    income = tx_query.filter(Transaction.type == "income").with_entities(db.func.sum(amount_expr)).scalar() or 0

    category_totals = summarize_category_totals(current_user.id, start, end)
    monthly = summarize_monthly_spend(current_user.id)
    monthly_ie = summarize_monthly_income_expense(current_user.id)
    balance_points = balance_over_time(current_user.id)
    budgets = budget_progress(current_user.id, date.today())
    remaining = total_balance(current_user.id, start, end)
    top_categories_30 = summarize_category_totals(
        current_user.id, date.today() - timedelta(days=30), date.today()
    )
    forecast = forecast_balance(current_user.id, 30)
    # burn rate and runway based on last 30 days
    today = date.today()
    start_30 = today - timedelta(days=30)
    net_30 = total_balance(current_user.id, start_30, today)
    daily_burn = abs(net_30 / 30.0) if net_30 < 0 else 0.0
    current_balance = balance_points[-1][1] if balance_points else remaining
    runway_days = int(current_balance / daily_burn) if daily_burn > 0 and current_balance > 0 else None
    # weekly deltas
    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end = this_week_start - timedelta(days=1)
    net_this_week = weekly_net(current_user.id, this_week_start, today)
    net_last_week = weekly_net(current_user.id, last_week_start, last_week_end)
    upcoming_recurring = (
        RecurringRule.query.filter_by(user_id=current_user.id)
        .order_by(RecurringRule.next_run.asc())
        .limit(5)
        .all()
    )
    cat_colors = {c.name: c.color for c in Category.query.filter_by(user_id=current_user.id).all()}

    recent_tx = (
        Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.date.desc()).limit(5).all()
    )
    goal = SavingsGoal.query.filter_by(user_id=current_user.id).first()
    goal_percent = 0
    if goal and goal.target_amount > 0:
        goal_percent = min(goal.current_amount / goal.target_amount * 100, 999)
    tx_count = Transaction.query.filter_by(user_id=current_user.id).count()
    budget_count = Budget.query.filter_by(user_id=current_user.id).count()

    return render_template(
        "dashboard.html",
        expenses=expenses,
        income=income,
        category_totals=category_totals,
        monthly=monthly,
        monthly_ie=monthly_ie,
        balance_points=balance_points,
        budgets=budgets,
        recent_tx=recent_tx,
        start=start_str,
        end=end_str,
        remaining=remaining,
        goal=goal,
        goal_percent=goal_percent,
        top_categories_30=top_categories_30,
        forecast=forecast,
        net_this_week=net_this_week,
        net_last_week=net_last_week,
        upcoming_recurring=upcoming_recurring,
        tx_count=tx_count,
        budget_count=budget_count,
        cat_colors=cat_colors,
        daily_burn=daily_burn,
        runway_days=runway_days,
        current_balance=current_balance,
    )


@main_bp.route("/transactions", methods=["GET", "POST"])
@login_required
def transactions():
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "save_preset":
            preset = {
                "start": request.form.get("start") or "",
                "end": request.form.get("end") or "",
                "category": request.form.get("category") or "",
                "sort": request.form.get("sort") or "date_desc",
                "range": request.form.get("range") or "",
            }
            if settings:
                settings.filter_preset = json.dumps(preset)
            else:
                settings = UserSettings(user_id=current_user.id, base_currency="USD", filter_preset=json.dumps(preset))
                db.session.add(settings)
            db.session.commit()
            flash("Filter preset saved to your account.", "success")
            return redirect(url_for("main.transactions", **preset))
        if action == "load_preset" and settings and settings.filter_preset:
            try:
                preset = json.loads(settings.filter_preset)
            except Exception:
                preset = {}
            return redirect(url_for("main.transactions", **preset))
        if action == "alerts":
            settings = settings or UserSettings(user_id=current_user.id, base_currency="USD")
            settings.alert_large = float(request.form.get("alert_large") or 0) or None
            settings.alert_budget_pct = float(request.form.get("alert_budget_pct") or 0) or None
            db.session.add(settings)
            db.session.commit()
            flash("Alerts updated.", "success")
            return redirect(url_for("main.settings"))
    sort = request.args.get("sort", "date_desc")
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    category = request.args.get("category") or None
    range_filter = request.args.get("range")
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = min(max(request.args.get("per_page", 20, type=int) or 20, 1), 100)

    if range_filter in ["this_week", "last_week"]:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        if range_filter == "this_week":
            start = monday
            end = today
        else:
            start = monday - timedelta(days=7)
            end = monday - timedelta(days=1)
    elif range_filter == "30d":
        end = date.today()
        start = end - timedelta(days=30)

    query = get_transactions_for_period(current_user.id, start, end, category)
    if sort == "amount_asc":
        query = query.order_by(Transaction.amount.asc())
    elif sort == "amount_desc":
        query = query.order_by(Transaction.amount.desc())
    elif sort == "date_asc":
        query = query.order_by(Transaction.date.asc())
    else:
        query = query.order_by(Transaction.date.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    transactions_list = pagination.items
    cat_colors = {c.name: c.color for c in Category.query.filter_by(user_id=current_user.id).all()}
    pagination_params = request.args.to_dict()
    pagination_params.pop("page", None)
    pagination_params.pop("per_page", None)
    return render_template(
        "transactions.html",
        transactions=transactions_list,
        pagination=pagination,
        categories=get_user_categories(current_user.id),
        selected_category=category,
        sort=sort,
        start=request.args.get("start"),
        end=request.args.get("end"),
        range_filter=range_filter,
        cat_colors=cat_colors,
        pagination_params=pagination_params,
        per_page=per_page,
    )


@main_bp.route("/transactions/add", methods=["GET", "POST"])
@login_required
def add_transaction():
    categories = get_user_categories(current_user.id)
    base_currency = user_base_currency(current_user.id)
    if request.method == "POST":
        t_date = _parse_date(request.form.get("date")) or date.today()
        t_type = request.form.get("type", "expense")
        category_input = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        category = _apply_category_rule(current_user.id, description, category_input or "Other")
        amount_raw = request.form.get("amount", "0").replace(",", "")
        currency = request.form.get("currency") or base_currency
        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Amount must be a number.", "danger")
            return render_template(
                "add_transaction.html",
                categories=categories,
                today=date.today().isoformat(),
                currencies=BASE_CURRENCIES,
                base_currency=base_currency,
            )

        if t_type not in ["expense", "income"]:
            flash("Transaction type is invalid.", "danger")
            return render_template(
                "add_transaction.html",
                categories=categories,
                today=date.today().isoformat(),
                currencies=BASE_CURRENCIES,
                base_currency=base_currency,
            )
        if amount <= 0:
            flash("Amount must be greater than zero.", "danger")
            return render_template(
                "add_transaction.html",
                categories=categories,
                today=date.today().isoformat(),
                currencies=BASE_CURRENCIES,
                base_currency=base_currency,
            )

        amount_base = convert_to_base(current_user.id, amount, currency)
        tx = Transaction(
            user_id=current_user.id,
            date=t_date,
            type=t_type,
            category=category,
            amount=amount,
            currency=currency,
            amount_base=amount_base,
            description=description,
        )
        db.session.add(tx)
        db.session.commit()
        _save_attachment(tx.id)
        settings = UserSettings.query.filter_by(user_id=current_user.id).first()
        _maybe_send_alerts(tx, settings=settings)
        _check_budget_alerts(tx, settings=settings)
        flash("Transaction added.", "success")
        return redirect(url_for("main.transactions"))

    return render_template(
        "add_transaction.html",
        categories=categories,
        today=date.today().isoformat(),
        currencies=BASE_CURRENCIES,
        base_currency=base_currency,
    )


@main_bp.route("/transactions/<int:tx_id>/edit", methods=["GET", "POST"])
@login_required
def edit_transaction(tx_id):
    tx = Transaction.query.filter_by(id=tx_id, user_id=current_user.id).first_or_404()
    categories = get_user_categories(current_user.id)
    base_currency = user_base_currency(current_user.id)
    if request.method == "POST":
        t_date = _parse_date(request.form.get("date")) or tx.date
        t_type = request.form.get("type", tx.type)
        category = request.form.get("category", tx.category).strip() or tx.category
        description = request.form.get("description", tx.description or "").strip()
        currency = request.form.get("currency", tx.currency or base_currency)
        try:
            amount = float(request.form.get("amount", tx.amount))
        except ValueError:
            flash("Amount must be a number.", "danger")
            return render_template(
                "edit_transaction.html",
                tx=tx,
                categories=categories,
                currencies=BASE_CURRENCIES,
                base_currency=base_currency,
            )

        if amount <= 0:
            flash("Amount must be greater than zero.", "danger")
            return render_template(
                "edit_transaction.html",
                tx=tx,
                categories=categories,
                currencies=BASE_CURRENCIES,
                base_currency=base_currency,
            )
        if t_type not in ["expense", "income"]:
            flash("Transaction type is invalid.", "danger")
            return render_template(
                "edit_transaction.html",
                tx=tx,
                categories=categories,
                currencies=BASE_CURRENCIES,
                base_currency=base_currency,
            )

        tx.date = t_date
        tx.type = t_type
        tx.category = category
        tx.amount = amount
        tx.currency = currency
        tx.amount_base = convert_to_base(current_user.id, amount, currency)
        tx.description = description
        db.session.commit()
        settings = UserSettings.query.filter_by(user_id=current_user.id).first()
        _save_attachment(tx.id)
        _check_budget_alerts(tx, settings=settings)
        flash("Transaction updated.", "success")
        return redirect(url_for("main.transactions"))

    return render_template(
        "edit_transaction.html",
        tx=tx,
        categories=categories,
        currencies=BASE_CURRENCIES,
        base_currency=base_currency,
    )


@main_bp.route("/transactions/<int:tx_id>/delete", methods=["POST"])
@login_required
def delete_transaction(tx_id):
    tx = Transaction.query.filter_by(id=tx_id, user_id=current_user.id).first_or_404()
    db.session.delete(tx)
    db.session.commit()
    flash("Transaction deleted.", "info")
    return redirect(url_for("main.transactions"))


@main_bp.route("/budgets", methods=["GET", "POST"])
@login_required
def budgets():
    if request.method == "POST":
        period_start = _parse_date(request.form.get("period_start"))
        period_end = _parse_date(request.form.get("period_end"))
        category = request.form.get("category") or None
        try:
            amount = float(request.form.get("amount", 0))
        except ValueError:
            flash("Amount must be numeric.", "danger")
            return redirect(url_for("main.budgets"))

        if not period_start or not period_end:
            flash("Please provide both start and end dates.", "danger")
            return redirect(url_for("main.budgets"))
        if period_end < period_start:
            flash("End date must be after start date.", "danger")
            return redirect(url_for("main.budgets"))
        if amount <= 0:
            flash("Budget amount must be greater than zero.", "danger")
            return redirect(url_for("main.budgets"))

        budget = Budget(
            user_id=current_user.id,
            period_start=period_start,
            period_end=period_end,
            category=category if category else None,
            amount=amount,
        )
        db.session.add(budget)
        db.session.commit()
        flash("Budget saved.", "success")
        return redirect(url_for("main.budgets"))

    budgets_list = Budget.query.filter_by(user_id=current_user.id).order_by(Budget.period_end.desc()).all()
    progress = budget_progress(current_user.id, date.today())
    return render_template("budgets.html", budgets=budgets_list, progress=progress, categories=get_user_categories(current_user.id))


@main_bp.route("/budgets/<int:budget_id>/edit", methods=["GET", "POST"])
@login_required
def edit_budget(budget_id):
    budget = Budget.query.filter_by(id=budget_id, user_id=current_user.id).first_or_404()
    if request.method == "POST":
        period_start = _parse_date(request.form.get("period_start")) or budget.period_start
        period_end = _parse_date(request.form.get("period_end")) or budget.period_end
        category = request.form.get("category") or None
        try:
            amount = float(request.form.get("amount", budget.amount))
        except ValueError:
            flash("Amount must be numeric.", "danger")
            return render_template("edit_budget.html", budget=budget, categories=get_user_categories(current_user.id))

        if period_end < period_start:
            flash("End date must be after start date.", "danger")
            return render_template("edit_budget.html", budget=budget, categories=get_user_categories(current_user.id))
        if amount <= 0:
            flash("Budget amount must be greater than zero.", "danger")
            return render_template("edit_budget.html", budget=budget, categories=get_user_categories(current_user.id))

        budget.period_start = period_start
        budget.period_end = period_end
        budget.category = category if category else None
        budget.amount = amount
        db.session.commit()
        flash("Budget updated.", "success")
        return redirect(url_for("main.budgets"))

    return render_template("edit_budget.html", budget=budget, categories=get_user_categories(current_user.id))


@main_bp.route("/budgets/<int:budget_id>/delete", methods=["POST"])
@login_required
def delete_budget(budget_id):
    budget = Budget.query.filter_by(id=budget_id, user_id=current_user.id).first_or_404()
    db.session.delete(budget)
    db.session.commit()
    flash("Budget removed.", "info")
    return redirect(url_for("main.budgets"))


@main_bp.route("/reports")
@login_required
def reports():
    category_totals = summarize_category_totals(current_user.id)
    monthly = summarize_monthly_spend(current_user.id)
    monthly_ie = summarize_monthly_income_expense(current_user.id)
    balance_points = balance_over_time(current_user.id)
    forecast = forecast_balance(current_user.id, 30)
    cat_colors = {c.name: c.color for c in Category.query.filter_by(user_id=current_user.id).all()}
    return render_template(
        "reports.html",
        category_totals=category_totals,
        monthly=monthly,
        monthly_ie=monthly_ie,
        balance_points=balance_points,
        forecast=forecast,
        cat_colors=cat_colors,
    )


@main_bp.route("/savings", methods=["GET", "POST"])
@login_required
def savings():
    goal = SavingsGoal.query.filter_by(user_id=current_user.id).first()
    if not goal:
        goal = SavingsGoal(user_id=current_user.id, name="My Savings Goal", target_amount=0, current_amount=0)
        db.session.add(goal)
        db.session.commit()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "set_target":
            try:
                target = float(request.form.get("target_amount", 0))
            except ValueError:
                flash("Target must be numeric.", "danger")
                return redirect(url_for("main.savings"))
            if target <= 0:
                flash("Target must be greater than zero.", "danger")
                return redirect(url_for("main.savings"))
            goal.target_amount = target
            db.session.commit()
            flash("Savings target updated.", "success")
        elif action == "add_contribution":
            try:
                add_amount = float(request.form.get("add_amount", 0))
            except ValueError:
                flash("Amount must be numeric.", "danger")
                return redirect(url_for("main.savings"))
            if add_amount <= 0:
                flash("Contribution must be greater than zero.", "danger")
                return redirect(url_for("main.savings"))
            goal.current_amount += add_amount
            db.session.commit()
            flash("Contribution added.", "success")
        return redirect(url_for("main.savings"))

    percent = 0
    if goal.target_amount > 0:
        percent = min(goal.current_amount / goal.target_amount * 100, 999)

    return render_template("savings.html", goal=goal, percent=percent)


@main_bp.route("/recurring", methods=["GET", "POST"])
@login_required
def recurring():
    categories = get_user_categories(current_user.id)
    base_currency = user_base_currency(current_user.id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        frequency = request.form.get("frequency", "monthly")
        r_type = request.form.get("type", "expense")
        category = request.form.get("category", "Other")
        currency = request.form.get("currency", base_currency)
        description = request.form.get("description", "").strip()
        start_date = _parse_date(request.form.get("start_date")) or date.today()
        try:
            amount = float(request.form.get("amount", 0))
        except ValueError:
            flash("Amount must be numeric.", "danger")
            return redirect(url_for("main.recurring"))
        if amount <= 0:
            flash("Amount must be greater than zero.", "danger")
            return redirect(url_for("main.recurring"))
        rule = RecurringRule(
            user_id=current_user.id,
            name=name or "Recurring",
            frequency=frequency,
            type=r_type,
            amount=amount,
            currency=currency,
            category=category,
            description=description,
            next_run=start_date,
        )
        db.session.add(rule)
        db.session.commit()
        flash("Recurring rule saved.", "success")
        return redirect(url_for("main.recurring"))

    rules = RecurringRule.query.filter_by(user_id=current_user.id).all()
    return render_template(
        "recurring.html",
        rules=rules,
        categories=categories,
        currencies=BASE_CURRENCIES,
        base_currency=base_currency,
        today=date.today().isoformat(),
    )


@main_bp.route("/attachments/<filename>")
@login_required
def attachment(filename):
    from finance_app.config import Config

    return send_from_directory(Config.UPLOAD_FOLDER, filename, as_attachment=True)


@main_bp.route("/transactions/import", methods=["GET", "POST"])
@login_required
def import_transactions():
    if request.method == "POST":
        file = request.files.get("csv_file")
        if not file or not file.filename.endswith(".csv"):
            flash("Please upload a CSV file.", "danger")
            return redirect(url_for("main.import_transactions"))
        content = file.read().decode("utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(content))
        count = 0
        for row in reader:
            try:
                t_date = _parse_date(row.get("date")) or date.today()
                t_type = row.get("type", "expense").lower()
                raw_cat = row.get("category", "") or "Other"
                amount = float(row.get("amount", 0))
                description = row.get("description", "")
                currency = row.get("currency") or user_base_currency(current_user.id)
            except Exception:
                continue
            if amount <= 0 or t_type not in ["expense", "income"]:
                continue
            category = _apply_category_rule(current_user.id, description, raw_cat)
            tx = Transaction(
                user_id=current_user.id,
                date=t_date,
                type=t_type,
                category=category,
                amount=amount,
                currency=currency,
                amount_base=convert_to_base(current_user.id, amount, currency),
                description=description,
            )
            db.session.add(tx)
            count += 1
        db.session.commit()
        flash(f"Imported {count} transactions.", "success")
        return redirect(url_for("main.transactions"))
    return render_template("import_transactions.html")


@main_bp.route("/recurring/<int:rule_id>/delete", methods=["POST"])
@login_required
def delete_recurring(rule_id):
    rule = RecurringRule.query.filter_by(id=rule_id, user_id=current_user.id).first_or_404()
    db.session.delete(rule)
    db.session.commit()
    flash("Recurring rule deleted.", "info")
    return redirect(url_for("main.recurring"))


@main_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    message = None
    categories_q = Category.query.filter_by(user_id=current_user.id).all()
    categories = [(c.name, c.color) for c in categories_q] if categories_q else [(c, None) for c in get_user_categories(current_user.id)]
    base_currency = user_base_currency(current_user.id)
    settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    if not settings:
        settings = UserSettings(user_id=current_user.id, base_currency="USD")
        db.session.add(settings)
        db.session.commit()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "password":
            current_pw = request.form.get("current_password", "")
            new_pw = request.form.get("new_password", "")
            from finance_app import bcrypt

            if not bcrypt.check_password_hash(current_user.password_hash, current_pw):
                flash("Current password is incorrect.", "danger")
            elif len(new_pw) < 6:
                flash("New password must be at least 6 characters.", "warning")
            else:
                current_user.password_hash = bcrypt.generate_password_hash(new_pw).decode("utf-8")
                db.session.commit()
                message = "Password updated."
                flash(message, "success")
        elif action == "base_currency":
            new_base = request.form.get("base_currency", "USD")
            settings.base_currency = new_base
            db.session.commit()
            flash("Base currency updated.", "success")
        elif action == "add_category":
            name = request.form.get("category_name", "").strip()
            color = request.form.get("category_color") or None
            if not name:
                flash("Category name required.", "danger")
            else:
                exists = Category.query.filter_by(user_id=current_user.id, name=name).first()
                if exists:
                    flash("Category already exists.", "warning")
                else:
                    db.session.add(Category(user_id=current_user.id, name=name, color=color))
                    db.session.commit()
                    flash("Category added.", "success")
        elif action == "add_rate":
            code = request.form.get("rate_code", "").strip().upper()
            try:
                rate_val = float(request.form.get("rate_value", 0))
            except ValueError:
                flash("Rate must be numeric.", "danger")
                return redirect(url_for("main.settings"))
            if not code or rate_val <= 0:
                flash("Provide a valid currency code and rate.", "danger")
            else:
                rate = CurrencyRate.query.filter_by(user_id=current_user.id, code=code).first()
                if not rate:
                    rate = CurrencyRate(user_id=current_user.id, code=code, rate_to_base=rate_val)
                    db.session.add(rate)
                else:
                    rate.rate_to_base = rate_val
                db.session.commit()
                flash("Rate saved.", "success")
        elif action == "alerts":
            settings.alert_large = float(request.form.get("alert_large") or 0) or None
            settings.alert_budget_pct = float(request.form.get("alert_budget_pct") or 0) or None
            db.session.commit()
            flash("Alerts updated.", "success")
        elif action == "add_rule":
            keyword = (request.form.get("rule_keyword") or "").strip()
            cat_choice = (request.form.get("rule_category") or "").strip()
            if not keyword or not cat_choice:
                flash("Keyword and category are required for a rule.", "danger")
            else:
                exists = CategoryRule.query.filter_by(user_id=current_user.id, keyword=keyword).first()
                if exists:
                    exists.category = cat_choice
                else:
                    db.session.add(CategoryRule(user_id=current_user.id, keyword=keyword, category=cat_choice))
                db.session.commit()
                flash("Category rule saved.", "success")
        elif action == "delete_rule":
            rule_id = request.form.get("rule_id")
            rule = CategoryRule.query.filter_by(id=rule_id, user_id=current_user.id).first()
            if rule:
                db.session.delete(rule)
                db.session.commit()
                flash("Rule deleted.", "info")
        return redirect(url_for("main.settings"))

    rates = CurrencyRate.query.filter_by(user_id=current_user.id).all()
    rules = CategoryRule.query.filter_by(user_id=current_user.id).order_by(CategoryRule.created_at.desc()).all()
    return render_template(
        "settings.html",
        message=message,
        categories=categories,
        base_currency=base_currency,
        rates=rates,
        currencies=BASE_CURRENCIES,
        settings=settings,
        rules=rules,
    )


def _export_transactions(user_id: int, start: date = None, end: date = None, category: str = None):
    query = get_transactions_for_period(user_id, start, end, category).order_by(Transaction.date)
    return query.all()


@main_bp.route("/export/csv")
@login_required
def export_csv():
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    category = request.args.get("category") or None
    transactions = _export_transactions(current_user.id, start, end, category)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Category", "Description", "Amount", "Currency", "Amount (Base)"])
    for tx in transactions:
        writer.writerow(
            [
                tx.date.isoformat(),
                tx.type,
                tx.category,
                tx.description or "",
                f"{tx.amount:.2f}",
                tx.currency or "",
                f"{(tx.amount_base if tx.amount_base is not None else tx.amount):.2f}",
            ]
        )
    output.seek(0)
    return Response(
        output.read(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )


@main_bp.route("/export/pdf")
@login_required
def export_pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    category = request.args.get("category") or None
    transactions = _export_transactions(current_user.id, start, end, category)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []
    elements.append(Paragraph("Transactions", styles["Heading1"]))
    elements.append(Spacer(1, 12))
    data = [["Date", "Type", "Category", "Description", "Amount", "Currency", "Amount (Base)"]]
    for tx in transactions:
        data.append(
            [
                tx.date.isoformat(),
                tx.type.title(),
                tx.category,
                tx.description or "",
                f"{tx.amount:.2f}",
                tx.currency or "",
                f"{(tx.amount_base if tx.amount_base is not None else tx.amount):.2f}",
            ]
        )
    table = Table(data)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b132b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
            ]
        )
    )
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="transactions.pdf", mimetype="application/pdf")
