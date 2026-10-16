from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(80), nullable=False, default="")
    password_hash = db.Column(db.String(255), nullable=False)
    auth_version = db.Column(db.Integer, nullable=False, default=1)
    onboarding_complete = db.Column(db.Boolean, nullable=False, default=False)
    notify_journal = db.Column(db.Boolean, nullable=False, default=True)
    notify_security = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    entries = db.relationship("JournalEntry", back_populates="owner", lazy="dynamic")
    notifications = db.relationship("Notification", back_populates="owner", lazy="dynamic")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class JournalEntry(db.Model):
    __tablename__ = "journal_entries"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    storage_key = db.Column(db.String(512), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(80), nullable=False)
    byte_size = db.Column(db.Integer, nullable=False)
    image_hash = db.Column(db.String(16), nullable=True, index=True)
    trade_date = db.Column(db.Date, nullable=False, index=True)
    symbol = db.Column(db.String(32), nullable=False, default="")
    market = db.Column(db.String(80), nullable=False, default="")
    reflection = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)
    owner = db.relationship("User", back_populates="entries")


class PasswordReset(db.Model):
    __tablename__ = "password_resets"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(32), nullable=False, default="journal")
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.String(240), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    read_at = db.Column(db.DateTime, nullable=True)
    owner = db.relationship("User", back_populates="notifications")
