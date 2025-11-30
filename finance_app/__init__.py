import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv

db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()


def create_app(test_config=None):
    load_dotenv()

    app = Flask(__name__, instance_relative_config=False, template_folder="../templates", static_folder="../static")
    app.config.from_object("finance_app.config.Config")
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    with app.app_context():
        # Local import to avoid circular dependencies
        from finance_app.routes import main_bp
        from finance_app.auth import auth_bp
        from finance_app.models import User, SavingsGoal, Category, CurrencyRate, UserSettings, RecurringRule
        from sqlalchemy import inspect, text

        db.create_all()

        # Ensure email column exists for existing databases without migrations
        inspector = inspect(db.engine)
        columns = [c["name"] for c in inspector.get_columns("users")]
        if "email" not in columns:
            try:
                db.session.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(120) UNIQUE"))
                db.session.commit()
            except Exception:
                db.session.rollback()
        if "role" not in columns:
            try:
                db.session.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user'"))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Ensure new columns on transactions
        tx_columns = [c["name"] for c in inspector.get_columns("transactions")]
        if "currency" not in tx_columns:
            try:
                db.session.execute(text("ALTER TABLE transactions ADD COLUMN currency VARCHAR(8)"))
                db.session.commit()
            except Exception:
                db.session.rollback()
        if "amount_base" not in tx_columns:
            try:
                db.session.execute(text("ALTER TABLE transactions ADD COLUMN amount_base FLOAT"))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Ensure new columns on categories
        cat_columns = [c["name"] for c in inspector.get_columns("categories")]
        if "color" not in cat_columns:
            try:
                db.session.execute(text("ALTER TABLE categories ADD COLUMN color VARCHAR(16)"))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Ensure new columns on user_settings
        settings_columns = []
        try:
            settings_columns = [c["name"] for c in inspector.get_columns("user_settings")]
        except Exception:
            pass
        if settings_columns and "filter_preset" not in settings_columns:
            try:
                db.session.execute(text("ALTER TABLE user_settings ADD COLUMN filter_preset TEXT"))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Ensure new tables exist (create_all already covers new DBs)
        existing_tables = inspector.get_table_names()
        if "savings_goals" not in existing_tables:
            db.create_all()
        for tbl in ["categories", "currency_rates", "user_settings", "recurring_rules"]:
            if tbl not in existing_tables:
                db.create_all()

        app.register_blueprint(auth_bp)
        app.register_blueprint(main_bp)

    return app
