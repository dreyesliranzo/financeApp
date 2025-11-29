from datetime import date, datetime

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
)
from flask_login import login_required, current_user

from finance_app import db
from finance_app.models import Transaction, Budget
from finance_app.services import (
    DEFAULT_CATEGORIES,
    get_transactions_for_period,
    summarize_category_totals,
    summarize_monthly_spend,
    balance_over_time,
    budget_progress,
    total_balance,
)

main_bp = Blueprint("main", __name__)


def _parse_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    start_str = request.args.get("start")
    end_str = request.args.get("end")
    start = _parse_date(start_str)
    end = _parse_date(end_str)

    tx_query = get_transactions_for_period(current_user.id, start, end)
    expenses = (
        tx_query.filter(Transaction.type == "expense").with_entities(db.func.sum(Transaction.amount)).scalar() or 0
    )
    income = (
        tx_query.filter(Transaction.type == "income").with_entities(db.func.sum(Transaction.amount)).scalar() or 0
    )

    category_totals = summarize_category_totals(current_user.id, start, end)
    monthly = summarize_monthly_spend(current_user.id)
    balance_points = balance_over_time(current_user.id)
    budgets = budget_progress(current_user.id, date.today())
    remaining = total_balance(current_user.id, start, end)

    recent_tx = (
        Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.date.desc()).limit(5).all()
    )

    return render_template(
        "dashboard.html",
        expenses=expenses,
        income=income,
        category_totals=category_totals,
        monthly=monthly,
        balance_points=balance_points,
        budgets=budgets,
        recent_tx=recent_tx,
        start=start_str,
        end=end_str,
        remaining=remaining,
    )


@main_bp.route("/transactions")
@login_required
def transactions():
    sort = request.args.get("sort", "date_desc")
    start = _parse_date(request.args.get("start"))
    end = _parse_date(request.args.get("end"))
    category = request.args.get("category") or None
    range_filter = request.args.get("range")

    if range_filter in ["this_week", "last_week"]:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        if range_filter == "this_week":
            start = monday
            end = today
        else:
            start = monday - timedelta(days=7)
            end = monday - timedelta(days=1)

    query = get_transactions_for_period(current_user.id, start, end, category)
    if sort == "amount_asc":
        query = query.order_by(Transaction.amount.asc())
    elif sort == "amount_desc":
        query = query.order_by(Transaction.amount.desc())
    elif sort == "date_asc":
        query = query.order_by(Transaction.date.asc())
    else:
        query = query.order_by(Transaction.date.desc())

    transactions_list = query.all()
    return render_template(
        "transactions.html",
        transactions=transactions_list,
        categories=DEFAULT_CATEGORIES,
        selected_category=category,
        sort=sort,
        start=request.args.get("start"),
        end=request.args.get("end"),
        range_filter=range_filter,
    )


@main_bp.route("/transactions/add", methods=["GET", "POST"])
@login_required
def add_transaction():
    if request.method == "POST":
        t_date = _parse_date(request.form.get("date")) or date.today()
        t_type = request.form.get("type", "expense")
        category = request.form.get("category", "").strip() or "Other"
        description = request.form.get("description", "").strip()
        amount_raw = request.form.get("amount", "0").replace(",", "")
        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Amount must be a number.", "danger")
            return render_template("add_transaction.html", categories=DEFAULT_CATEGORIES, today=date.today().isoformat())

        if t_type not in ["expense", "income"]:
            flash("Transaction type is invalid.", "danger")
            return render_template("add_transaction.html", categories=DEFAULT_CATEGORIES, today=date.today().isoformat())
        if amount <= 0:
            flash("Amount must be greater than zero.", "danger")
            return render_template("add_transaction.html", categories=DEFAULT_CATEGORIES, today=date.today().isoformat())

        tx = Transaction(
            user_id=current_user.id,
            date=t_date,
            type=t_type,
            category=category,
            amount=amount,
            description=description,
        )
        db.session.add(tx)
        db.session.commit()
        flash("Transaction added.", "success")
        return redirect(url_for("main.transactions"))

    return render_template("add_transaction.html", categories=DEFAULT_CATEGORIES, today=date.today().isoformat())


@main_bp.route("/transactions/<int:tx_id>/edit", methods=["GET", "POST"])
@login_required
def edit_transaction(tx_id):
    tx = Transaction.query.filter_by(id=tx_id, user_id=current_user.id).first_or_404()
    if request.method == "POST":
        t_date = _parse_date(request.form.get("date")) or tx.date
        t_type = request.form.get("type", tx.type)
        category = request.form.get("category", tx.category).strip() or tx.category
        description = request.form.get("description", tx.description or "").strip()
        try:
            amount = float(request.form.get("amount", tx.amount))
        except ValueError:
            flash("Amount must be a number.", "danger")
            return render_template("edit_transaction.html", tx=tx, categories=DEFAULT_CATEGORIES)

        if amount <= 0:
            flash("Amount must be greater than zero.", "danger")
            return render_template("edit_transaction.html", tx=tx, categories=DEFAULT_CATEGORIES)
        if t_type not in ["expense", "income"]:
            flash("Transaction type is invalid.", "danger")
            return render_template("edit_transaction.html", tx=tx, categories=DEFAULT_CATEGORIES)

        tx.date = t_date
        tx.type = t_type
        tx.category = category
        tx.amount = amount
        tx.description = description
        db.session.commit()
        flash("Transaction updated.", "success")
        return redirect(url_for("main.transactions"))

    return render_template("edit_transaction.html", tx=tx, categories=DEFAULT_CATEGORIES)


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
    return render_template("budgets.html", budgets=budgets_list, progress=progress, categories=DEFAULT_CATEGORIES)


@main_bp.route("/savings", methods=["GET", "POST"])
@login_required
def savings():
    from finance_app.models import SavingsGoal

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
            return render_template("edit_budget.html", budget=budget, categories=DEFAULT_CATEGORIES)

        if period_end < period_start:
            flash("End date must be after start date.", "danger")
            return render_template("edit_budget.html", budget=budget, categories=DEFAULT_CATEGORIES)
        if amount <= 0:
            flash("Budget amount must be greater than zero.", "danger")
            return render_template("edit_budget.html", budget=budget, categories=DEFAULT_CATEGORIES)

        budget.period_start = period_start
        budget.period_end = period_end
        budget.category = category if category else None
        budget.amount = amount
        db.session.commit()
        flash("Budget updated.", "success")
        return redirect(url_for("main.budgets"))

    return render_template("edit_budget.html", budget=budget, categories=DEFAULT_CATEGORIES)


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
    balance_points = balance_over_time(current_user.id)
    return render_template(
        "reports.html",
        category_totals=category_totals,
        monthly=monthly,
        balance_points=balance_points,
    )


@main_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    message = None
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        if not current_user or not current_user.password_hash:
            flash("No user found.", "danger")
        elif not current_user or not db.session:
            flash("Unexpected error.", "danger")
        elif not current_user.username:
            flash("Invalid user.", "danger")
        else:
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
    return render_template("settings.html", message=message)
