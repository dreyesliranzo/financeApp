from datetime import datetime, timedelta
import re
import secrets

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from finance_app import db, bcrypt
from finance_app.models import User, PasswordReset
from finance_app.email_utils import send_email

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
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        errors = _validate_credentials(username, password)
        if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            errors.append("Please provide a valid email.")
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("register.html")

        existing = User.query.filter_by(username=username).first()
        if existing:
            flash("Username already exists. Please choose another.", "warning")
            return render_template("register.html")
        if User.query.filter_by(email=email).first():
            flash("Email already linked to an account.", "warning")
            return render_template("register.html")

        password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
        user = User(username=username, email=email, password_hash=password_hash, created_at=datetime.utcnow())
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


def _generate_reset_token() -> str:
    return secrets.token_urlsafe(32)


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Please enter a valid email.", "danger")
            return render_template("forgot_password.html")

        user = User.query.filter_by(email=email).first()
        # Always respond the same to avoid leaking which emails exist
        flash("If an account exists for this email, you will receive a reset link.", "info")

        if user:
            token = _generate_reset_token()
            expires_at = datetime.utcnow() + timedelta(hours=1)
            reset = PasswordReset(user_id=user.id, token=token, expires_at=expires_at, used=False)
            db.session.add(reset)
            db.session.commit()
            reset_link = url_for("auth.reset_password", token=token, _external=True)
            email_body = (
                f"Hi {user.username},\n\n"
                f"We received a request to reset your password. Use the link below within 1 hour:\n\n"
                f"{reset_link}\n\n"
                "If you did not request this, you can ignore this email."
            )
            err = send_email(user.email, "Reset your Pulse Finance password", email_body)
            if err:
                # Log fallback for admins
                print(f"[Password reset][email failed] user={user.username} email={user.email} token={token} err={err}")
            else:
                print(f"[Password reset][email sent] user={user.username} email={user.email}")
        return redirect(url_for("auth.login"))
    return render_template("forgot_password.html")


@auth_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    reset = PasswordReset.query.filter_by(token=token, used=False).first()
    if not reset or reset.expires_at < datetime.utcnow():
        flash("Reset link is invalid or expired.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "warning")
            return render_template("reset_password.html", token=token)
        reset.user.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
        reset.used = True
        db.session.commit()
        flash("Password updated. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.html", token=token)


@auth_bp.route("/forgot-username", methods=["GET", "POST"])
def forgot_username():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Please enter a valid email.", "danger")
            return render_template("forgot_username.html")

        user = User.query.filter_by(email=email).first()
        flash("If an account exists for this email, we sent the username.", "info")
        if user:
            email_body = (
                f"Hi {user.username},\n\n"
                f"Your username for Pulse Finance is: {user.username}\n\n"
                "If you did not request this, you can ignore this email."
            )
            err = send_email(user.email, "Your Pulse Finance username", email_body)
            if err:
                print(f"[Username reminder][email failed] email={email} username={user.username} err={err}")
            else:
                print(f"[Username reminder][email sent] email={email} username={user.username}")
        return redirect(url_for("auth.login"))
    return render_template("forgot_username.html")
