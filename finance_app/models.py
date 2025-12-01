from datetime import datetime, date
from typing import Optional

from flask_login import UserMixin

from finance_app import db, login_manager


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    role = db.Column(db.String(20), default="user")  # basic roles: user/admin

    transactions = db.relationship("Transaction", backref="user", lazy=True, cascade="all, delete-orphan")
    budgets = db.relationship("Budget", backref="user", lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username}>"


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    return User.query.get(int(user_id))


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    type = db.Column(db.String(10), nullable=False)  # "expense" or "income"
    category = db.Column(db.String(80), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(8), nullable=True, default="USD")
    amount_base = db.Column(db.Float, nullable=True)  # converted to base currency
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Transaction {self.type} {self.amount}>"


class Budget(db.Model):
    __tablename__ = "budgets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    category = db.Column(db.String(80), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        label = self.category or "overall"
        return f"<Budget {label}: {self.amount}>"


class PasswordReset(db.Model):
    __tablename__ = "password_resets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token = db.Column(db.String(128), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("reset_tokens", lazy=True, cascade="all, delete-orphan"))


class SavingsGoal(db.Model):
    __tablename__ = "savings_goals"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(120), default="My Savings Goal")
    target_amount = db.Column(db.Float, nullable=False, default=0)
    current_amount = db.Column(db.Float, nullable=False, default=0)
    deadline = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("savings_goal", uselist=False, cascade="all, delete-orphan"))


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    color = db.Column(db.String(16), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "name", name="uq_category_user_name"),)

    user = db.relationship("User", backref=db.backref("categories", lazy=True, cascade="all, delete-orphan"))


class CurrencyRate(db.Model):
    __tablename__ = "currency_rates"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    code = db.Column(db.String(8), nullable=False)
    rate_to_base = db.Column(db.Float, nullable=False, default=1.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "code", name="uq_rate_user_code"),)

    user = db.relationship("User", backref=db.backref("currency_rates", lazy=True, cascade="all, delete-orphan"))


class UserSettings(db.Model):
    __tablename__ = "user_settings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    base_currency = db.Column(db.String(8), nullable=False, default="USD")
    filter_preset = db.Column(db.Text, nullable=True)
    alert_large = db.Column(db.Float, nullable=True)  # threshold for large tx alerts
    alert_budget_pct = db.Column(db.Float, nullable=True)  # e.g., 90 for 90%
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("settings", uselist=False, cascade="all, delete-orphan"))


class RecurringRule(db.Model):
    __tablename__ = "recurring_rules"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # expense/income
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(8), nullable=True, default="USD")
    category = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text)
    frequency = db.Column(db.String(20), nullable=False)  # daily/weekly/monthly
    next_run = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("recurring_rules", lazy=True, cascade="all, delete-orphan"))


class Attachment(db.Model):
    __tablename__ = "attachments"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transactions.id"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transaction = db.relationship("Transaction", backref=db.backref("attachments", lazy=True, cascade="all, delete-orphan"))


class CategoryRule(db.Model):
    __tablename__ = "category_rules"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    keyword = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "keyword", name="uq_rule_user_keyword"),)

    user = db.relationship("User", backref=db.backref("category_rules", lazy=True, cascade="all, delete-orphan"))
