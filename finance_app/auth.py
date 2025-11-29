from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from finance_app import db, bcrypt
from finance_app.models import User

auth_bp = Blueprint("auth", __name__)


def _validate_credentials(username: str, password: str):
    errors = []
    if not username or len(username) < 3:
        errors.append("Username must be at least 3 characters.")
    if not password or len(password) < 6:
        errors.append("Password must be at least 6 characters.")
    return errors


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        errors = _validate_credentials(username, password)
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("register.html")

        existing = User.query.filter_by(username=username).first()
        if existing:
            flash("Username already exists. Please choose another.", "warning")
            return render_template("register.html")

        password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
        user = User(username=username, password_hash=password_hash, created_at=datetime.utcnow())
        db.session.add(user)
        db.session.commit()
        flash("Account created. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if not user:
            flash("User not found. Please register first.", "danger")
            return render_template("login.html")
        if not bcrypt.check_password_hash(user.password_hash, password):
            flash("Incorrect password. Try again.", "danger")
            return render_template("login.html")

        login_user(user, remember=True)
        flash("Welcome back!", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for("auth.login"))
