from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from sqlalchemy.engine import make_url

from tradevault import _database_connection_settings, create_app, db
from tradevault.models import JournalEntry, Notification, PasswordReset, User


class TradeVaultTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "LOCAL_UPLOAD_FOLDER": str(Path(self.temp.name) / "uploads"),
            "LOCAL_STORAGE_ENABLED": True,
            "FORCE_LOCAL_STORAGE_FOR_TESTS": True,
            "SESSION_COOKIE_SECURE": False,
            "MAIL_SERVER": None,
            "MAIL_DEFAULT_SENDER": None,
        })
        with self.app.app_context():
            db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp.cleanup()

    def register(self, client=None, email="reader@example.com", password="a-secure-passphrase"):
        if client is None:
            client = self.client
        return client.post("/auth/register", data={
            "display_name": "Reader", "email": email, "password": password,
            "confirm_password": password,
        }, follow_redirects=True)

    def upload_png(self, client=None, symbol="ES", note="Waited for the retest"):
        if client is None:
            client = self.client
        image = Image.new("RGB", (90, 70), color=(42, 120, 88))
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        stream.seek(0)
        return client.post("/capture", data={
            "screenshot": (stream, f"{symbol.lower()}-chart.png"),
            "trade_date": date.today().isoformat(), "symbol": symbol,
            "market": "Futures", "reflection": note,
        }, content_type="multipart/form-data", follow_redirects=False)

    def complete_onboarding(self, client=None):
        if client is None:
            client = self.client
        return client.post("/onboarding")

    def test_account_onboarding_private_journal_and_health(self):
        self.assertFalse(self.app.config["SESSION_COOKIE_SECURE"])
        self.assertEqual(self.app.config["SESSION_COOKIE_SAMESITE"], "Lax")
        response = self.register()
        self.assertEqual(response.request.path, "/onboarding")
        self.assertIn(b"Your journal is private", response.data)
        self.assertEqual(self.client.get("/").status_code, 302)
        self.complete_onboarding()
        self.assertIn(b"Recent moments", self.client.get("/").data)
        health = self.client.get("/_app/health").get_json()
        assert health is not None
        self.assertEqual(health["status"], "ok")
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get("/").status_code, 302)

    def test_journal_paginates_older_entries_and_keeps_total_counts(self):
        self.register()
        self.complete_onboarding()
        with self.app.app_context():
            user = db.session.scalar(db.select(User).where(User.email == "reader@example.com"))
            db.session.add_all([
                JournalEntry(
                    user_id=user.id, storage_key=f"test/{index}.png", original_name=f"chart-{index}.png",
                    mime_type="image/png", byte_size=1, trade_date=date.today() - timedelta(days=index),
                )
                for index in range(31)
            ])
            db.session.commit()
        first = self.client.get("/")
        self.assertIn(b"Showing 1\xe2\x80\x9330 of 31 moments", first.data)
        self.assertIn(b"Older", first.data)
        second = self.client.get("/?page=2")
        self.assertIn(b"Showing 31\xe2\x80\x9331 of 31 moments", second.data)
        self.assertIn(b"Page 2 of 2", second.data)

    def test_upload_autosave_day_similarity_and_private_downloads(self):
        self.register()
        self.complete_onboarding()
        first = self.upload_png()
        self.assertEqual(first.status_code, 302)
        entry_url = first.headers["Location"]
        first_id = int(entry_url.rstrip("/").split("/")[-1])
        self.assertEqual(self.client.get(entry_url).status_code, 200)
        saved = self.client.post(f"/entry/{first_id}/update", json={"reflection": "Reviewed the retest patiently."})
        saved_data = saved.get_json()
        assert saved_data is not None
        self.assertTrue(saved_data["saved"])
        second = self.upload_png(symbol="ES2", note="Same chart family")
        self.assertEqual(second.status_code, 302)
        review = self.client.get("/review")
        self.assertEqual(review.status_code, 200)
        self.assertIn(b"Similar screenshots", review.data)
        image = self.client.get(f"/media/{first_id}")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.mimetype, "image/png")
        image.close()
        bundle = self.client.post("/downloads", data={"entry_ids": [str(first_id)]})
        self.assertEqual(bundle.status_code, 200)
        self.assertEqual(bundle.mimetype, "application/zip")

    def test_user_cannot_read_another_users_screenshot(self):
        self.register()
        self.complete_onboarding()
        response = self.upload_png()
        first_id = int(response.headers["Location"].rstrip("/").split("/")[-1])
        other = self.app.test_client()
        self.register(other, "another@example.com", "a-different-passphrase")
        self.complete_onboarding(other)
        self.assertEqual(other.get(f"/entry/{first_id}").status_code, 404)
        self.assertEqual(other.get(f"/media/{first_id}").status_code, 404)

    def test_password_recovery_does_not_enumerate_accounts(self):
        self.register()
        known = self.client.post("/auth/forgot-password", data={"email": "reader@example.com"})
        unknown = self.client.post("/auth/forgot-password", data={"email": "absent@example.com"})
        self.assertEqual(known.status_code, 200)
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(known.data, unknown.data)
        self.assertIn(b"not set up yet", known.data)

    def test_email_reset_token_is_hashed_single_use_and_changes_password(self):
        self.register()
        self.app.config.update(MAIL_SERVER="smtp.example", MAIL_DEFAULT_SENDER="journal@example.com")
        with patch("tradevault.auth._send_reset_email") as send:
            response = self.client.post("/auth/forgot-password", data={"email": "reader@example.com"})
            self.assertEqual(response.status_code, 200)
            token = send.call_args.args[1]
        with self.app.app_context():
            reset = db.session.scalar(db.select(PasswordReset))
            self.assertEqual(reset.token_hash, hashlib.sha256(token.encode()).hexdigest())
            self.assertNotEqual(reset.token_hash, token)
        self.assertEqual(self.client.get(f"/auth/reset-password/{token}").status_code, 200)
        changed = self.client.post(f"/auth/reset-password/{token}", data={
            "password": "replacement-passphrase", "confirm_password": "replacement-passphrase",
        })
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(self.client.get(f"/auth/reset-password/{token}").status_code, 302)
        self.assertEqual(self.client.post("/auth/login", data={"email": "reader@example.com", "password": "a-secure-passphrase"}).status_code, 200)
        self.assertEqual(self.client.post("/auth/login", data={"email": "reader@example.com", "password": "replacement-passphrase"}).status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(Notification).where(Notification.kind == "security")).title, "Password updated")

    def test_password_change_invalidates_session_and_creates_security_notice(self):
        self.register()
        self.complete_onboarding()
        response = self.client.post("/auth/change-password", data={
            "current_password": "a-secure-passphrase", "new_password": "new-secure-passphrase",
            "confirm_password": "new-secure-passphrase",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertEqual(self.client.post("/auth/login", data={"email": "reader@example.com", "password": "new-secure-passphrase"}).status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(Notification).where(Notification.kind == "security")).title, "Password updated")

    def test_profile_and_notification_forms_do_not_clear_each_other(self):
        self.register()
        self.client.post("/settings", data={"section": "profile", "display_name": "Market Reader"})
        with self.app.app_context():
            user = db.session.scalar(db.select(User).where(User.email == "reader@example.com"))
            self.assertEqual(user.display_name, "Market Reader")
            self.assertTrue(user.notify_journal)
        self.client.post("/settings", data={"section": "notifications", "notify_security": "on"})
        with self.app.app_context():
            user = db.session.scalar(db.select(User).where(User.email == "reader@example.com"))
            self.assertEqual(user.display_name, "Market Reader")
            self.assertFalse(user.notify_journal)
            self.assertTrue(user.notify_security)

    def test_file_type_rejected_and_logout(self):
        self.register()
        self.complete_onboarding()
        response = self.client.post("/capture", data={
            "screenshot": (io.BytesIO(b"not an image"), "fake.png"),
            "trade_date": date.today().isoformat(),
        }, content_type="multipart/form-data", follow_redirects=True)
        self.assertIn(b"Upload a valid PNG", response.data)
        self.client.post("/auth/logout")
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_managed_mysql_ssl_url_is_normalized_for_pymysql(self):
        uri, options = _database_connection_settings(
            "mysql://reader:secret@mysql.invalid/tradevault?ssl=%7B%22rejectUnauthorized%22%3Atrue%7D"
        )
        self.assertEqual(make_url(uri).query, {})
        self.assertTrue(options["connect_args"]["ssl"]["check_hostname"])
        self.assertTrue(Path(options["connect_args"]["ssl"]["ca"]).is_file())


if __name__ == "__main__":
    unittest.main()
