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
        from finance_app.models import User
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

        app.register_blueprint(auth_bp)
        app.register_blueprint(main_bp)

    return app
