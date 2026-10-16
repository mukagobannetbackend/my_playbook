from __future__ import annotations

import os
import secrets
from datetime import timedelta
from pathlib import Path

import certifi
from flask import Flask, jsonify, request, session
from flask_login import current_user
from flask_mail import Mail
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy.engine import make_url
from werkzeug.middleware.proxy_fix import ProxyFix

from .extensions import db, login_manager, mail, migrate, csrf


def _database_uri() -> str:
    uri = os.getenv("TRADEVAULT_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not uri:
        return "sqlite:///tradevault.sqlite3"
    if uri.startswith("mysql://"):
        uri = uri.replace("mysql://", "mysql+pymysql://", 1)
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    return uri


def _database_connection_settings(uri: str) -> tuple[str, dict]:
    """Adapt the managed Node-style SSL query to PyMySQL's verified TLS contract."""
    if uri.startswith("mysql://"):
        uri = uri.replace("mysql://", "mysql+pymysql://", 1)
    if not uri.startswith("mysql+pymysql://"):
        return uri, {"pool_pre_ping": True}
    parsed = make_url(uri)
    query = dict(parsed.query)
    policy = query.pop("ssl", None)
    if isinstance(policy, str):
        try:
            import json

            policy = json.loads(policy)
        except (TypeError, ValueError):
            policy = {"enabled": policy.lower() not in ("false", "0", "off", "disable")}
    if isinstance(policy, dict) and policy.get("rejectUnauthorized") is False:
        raise RuntimeError("TradeVault requires verified TLS for the managed MySQL connection.")
    parsed = parsed.set(query=query)
    return parsed.render_as_string(hide_password=False), {
        "pool_pre_ping": True,
        "connect_args": {"ssl": {"ca": certifi.where(), "check_hostname": True}},
    }


def _local_secret(instance_path: str) -> str:
    path = Path(instance_path) / ".local-session-key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip()


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    environment = os.getenv("TRADEVAULT_ENV", "development").lower()
    cookie_secure = os.getenv("TRADEVAULT_COOKIE_SECURE", "true").lower() == "true"
    secret = os.getenv("TRADEVAULT_SECRET_KEY")
    if test_config and test_config.get("TESTING"):
        secret = test_config.get("SECRET_KEY", "test-only-secret-key")
    if not secret:
        if environment == "production":
            raise RuntimeError("Set TRADEVAULT_SECRET_KEY to a stable high-entropy value before production startup.")
        secret = _local_secret(app.instance_path)

    app.config.update(
        SECRET_KEY=secret,
        SQLALCHEMY_DATABASE_URI=_database_uri(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_NAME="tradevault_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=cookie_secure,
        SESSION_COOKIE_SAMESITE="None" if cookie_secure else "Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        WTF_CSRF_TIME_LIMIT=7200,
        MAIL_SERVER=os.getenv("MAIL_SERVER"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_USE_TLS=os.getenv("MAIL_USE_TLS", "true").lower() == "true",
        MAIL_USE_SSL=os.getenv("MAIL_USE_SSL", "false").lower() == "true",
        MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
        MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER"),
        PASSWORD_RESET_MINUTES=int(os.getenv("PASSWORD_RESET_MINUTES", "60")),
        APP_BASE_URL=os.getenv("APP_BASE_URL", "").rstrip("/"),
        TRADEVAULT_ENV=environment,
        LOCAL_UPLOAD_FOLDER=os.getenv("LOCAL_UPLOAD_FOLDER", str(Path(app.instance_path) / "uploads")),
        LOCAL_STORAGE_ENABLED=os.getenv("LOCAL_STORAGE_ENABLED", "true").lower() == "true",
        SIMILARITY_DISTANCE=int(os.getenv("SIMILARITY_DISTANCE", "10")),
        TRUSTED_HOSTS=[h.strip() for h in os.getenv("TRADEVAULT_TRUSTED_HOSTS", "").split(",") if h.strip()] or None,
    )
    if test_config:
        app.config.update(test_config)
    app.config["SQLALCHEMY_DATABASE_URI"], app.config["SQLALCHEMY_ENGINE_OPTIONS"] = _database_connection_settings(
        app.config["SQLALCHEMY_DATABASE_URI"]
    )
    if app.config.get("TESTING"):
        app.config["SESSION_COOKIE_SECURE"] = False
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        app.config["WTF_CSRF_ENABLED"] = False

    # Public HTTPS terminates upstream of the Flask process. No frame-denying headers are set.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Sign in to open your journal."
    mail.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    from . import models  # noqa: F401
    from .auth import auth_bp
    from .journal import journal_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(journal_bp)

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            user = db.session.get(models.User, int(user_id))
        except (TypeError, ValueError):
            return None
        if user is None or str(user.auth_version) != str(session.get("auth_version", "")):
            return None
        return user

    @app.get("/_app/health")
    def health():
        return jsonify(status="ok", service="tradevault"), 200

    @app.get("/manus-routes.json")
    def route_manifest():
        from flask import send_from_directory

        return send_from_directory(str(Path(app.root_path).parent / "public"), "manus-routes.json", mimetype="application/json")

    @app.after_request
    def private_defaults(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.endpoint and request.endpoint != "static":
            response.headers["Cache-Control"] = "private, no-store, max-age=0"
        return response

    @app.errorhandler(413)
    def too_large(_error):
        message = "That image is larger than the 16 MB upload limit."
        return (jsonify(error=message), 413) if request.path.startswith("/api/") else (message, 413)

    @app.errorhandler(CSRFError)
    def csrf_error(_error):
        return "Your form expired. Refresh the page and try again.", 400

    @app.context_processor
    def nav_context():
        unread = 0
        if current_user.is_authenticated:
            unread = current_user.notifications.filter_by(read_at=None).count()
        return {"unread_notifications": unread}

    return app


__all__ = ["create_app", "db"]
