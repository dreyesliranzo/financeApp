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

        db.create_all()

        app.register_blueprint(auth_bp)
        app.register_blueprint(main_bp)

    return app
