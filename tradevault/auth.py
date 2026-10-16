from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_mail import Message
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from .extensions import db, mail
from .models import Notification, PasswordReset, User, utcnow


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _mail_ready() -> bool:
    return all(current_app.config.get(k) for k in ("MAIL_SERVER", "MAIL_DEFAULT_SENDER"))


def _reset_link(token: str) -> str:
    base = current_app.config.get("APP_BASE_URL")
    if not base and current_app.config["TRADEVAULT_ENV"] == "production":
        raise RuntimeError("Set APP_BASE_URL to the public HTTPS origin to send secure password-reset links.")
    return f"{base or request.url_root.rstrip('/')}{url_for('auth.reset_password', token=token)}"


def _send_reset_email(user: User, token: str) -> None:
    url = _reset_link(token)
    message = Message(
        subject="Reset your TradeVault password",
        recipients=[user.email],
        body=(f"Hi {user.display_name or 'there'},\n\nUse this one-time link to choose a new TradeVault password. "
              f"It expires in {current_app.config['PASSWORD_RESET_MINUTES']} minutes.\n\n{url}\n\n"
              "If you did not request this, you can ignore this email."),
    )
    mail.send(message)


def _finish_login(user: User) -> None:
    session.clear()
    login_user(user, remember=False, fresh=True)
    session.permanent = True
    session["auth_version"] = str(user.auth_version)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("journal.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("display_name", "").strip()[:80]
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if "@" not in email or len(email) > 254:
            flash("Enter a valid email address.", "error")
        elif len(password) < 10 or len(password) > 1024:
            flash("Choose a password between 10 and 1,024 characters.", "error")
        elif password != confirm:
            flash("Those passwords do not match.", "error")
        elif db.session.scalar(db.select(User.id).where(func.lower(User.email) == email)):
            flash("An account already uses that email. Sign in instead.", "error")
        else:
            user = User(email=email, display_name=name)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            _finish_login(user)
            flash("Your private journal is ready. Start with one screenshot or a small note.", "success")
            return redirect(url_for("journal.onboarding"))
    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("journal.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(db.select(User).where(func.lower(User.email) == email))
        if user and user.check_password(password):
            _finish_login(user)
            destination = "journal.onboarding" if not user.onboarding_complete else "journal.index"
            return redirect(url_for(destination))
        flash("That email and password combination was not recognized.", "error")
    return render_template("auth/login.html")


@auth_bp.post("/logout")
def logout():
    logout_user()
    session.clear()
    flash("You’re signed out. Your journal stays saved.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = db.session.scalar(db.select(User).where(func.lower(User.email) == email)) if email else None
        mail_ready = _mail_ready()
        # Same success copy for known and unknown accounts prevents address enumeration.
        if user and mail_ready:
            recent = db.session.scalar(db.select(PasswordReset.id).where(
                PasswordReset.user_id == user.id,
                PasswordReset.created_at > utcnow() - timedelta(minutes=5),
            ).limit(1))
            if not recent:
                token = secrets.token_urlsafe(32)
                expires = utcnow() + timedelta(minutes=current_app.config["PASSWORD_RESET_MINUTES"])
                db.session.execute(db.update(PasswordReset).where(
                    PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
                ).values(used_at=utcnow()))
                reset_record = PasswordReset(user_id=user.id, token_hash=_digest(token), expires_at=expires)
                db.session.add(reset_record)
                db.session.commit()
                try:
                    _send_reset_email(user, token)
                except Exception:
                    current_app.logger.exception("Password recovery email could not be sent")
                    # Keep response text identical for known and unknown addresses.
                    reset_record.used_at = utcnow()
                    db.session.commit()
        if not mail_ready:
            current_app.logger.warning("Password reset requested but email delivery is not configured")
            flash("Password recovery email is not set up yet. Ask the workspace owner to configure an email sender.", "info")
        else:
            flash("If an account matches that address, a recovery link will arrive by email shortly.", "success")
        return render_template("auth/forgot.html")
    return render_template("auth/forgot.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    reset = db.session.scalar(db.select(PasswordReset).where(PasswordReset.token_hash == _digest(token)))
    if not reset or reset.used_at or reset.expires_at < utcnow():
        flash("That recovery link has expired or was already used. Request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 10 or len(password) > 1024:
            flash("Choose a password between 10 and 1,024 characters.", "error")
        elif password != confirm:
            flash("Those passwords do not match.", "error")
        else:
            user = db.session.get(User, reset.user_id)
            user.set_password(password)
            user.auth_version += 1
            reset.used_at = utcnow()
            db.session.execute(db.update(PasswordReset).where(
                PasswordReset.user_id == user.id, PasswordReset.id != reset.id, PasswordReset.used_at.is_(None)
            ).values(used_at=utcnow()))
            if user.notify_security:
                db.session.add(Notification(user_id=user.id, kind="security", title="Password updated", body="Your account password was changed."))
            db.session.commit()
            flash("Your password has been updated. Sign in with your new one.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html")


@auth_bp.post("/change-password")
@login_required
def change_password():
    old = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if not current_user.check_password(old):
        flash("Your current password did not match.", "error")
    elif len(new) < 10 or len(new) > 1024:
        flash("Choose a password between 10 and 1,024 characters.", "error")
    elif new != confirm:
        flash("Those new passwords do not match.", "error")
    else:
        current_user.set_password(new)
        current_user.auth_version += 1
        if current_user.notify_security:
            db.session.add(Notification(user_id=current_user.id, kind="security", title="Password updated", body="Your account password was changed."))
        db.session.commit()
        logout_user()
        session.clear()
        flash("Password updated. Please sign in again with the new one.", "success")
        return redirect(url_for("auth.login"))
    return redirect(url_for("journal.settings"))
