from __future__ import annotations

import io
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import cast

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, url_for
from flask_login import current_user, login_required
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_

from .extensions import db
from .models import JournalEntry, Notification, User, utcnow
from .storage import StorageUnavailable, get_object_url, new_key, put_object, read_object

journal_bp = Blueprint("journal", __name__)
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
PROMPTS = [
    "What did you notice before the entry?",
    "Which part of this setup felt clear, and which part felt uncertain?",
    "What would you want future-you to remember about this moment?",
    "If you could replay one decision, what would you pay attention to?",
    "What did the market do that you didn’t expect?",
]


def _owned(entry_id: int, include_deleted: bool = False) -> JournalEntry:
    query = db.select(JournalEntry).where(JournalEntry.id == entry_id, JournalEntry.user_id == current_user.id)
    if not include_deleted:
        query = query.where(JournalEntry.deleted_at.is_(None))
    entry = db.session.scalar(query)
    if not entry:
        abort(404)
    return entry


def _average_hash(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
        pixels = [cast(int, image.getpixel((x, y))) for y in range(8) for x in range(8)]
    mean = sum(pixels) / len(pixels)
    return f"{sum((1 << i) for i, pixel in enumerate(pixels) if pixel >= mean):016x}"


def _today_entries():
    return db.session.scalars(db.select(JournalEntry).where(
        JournalEntry.user_id == current_user.id, JournalEntry.deleted_at.is_(None)
    ).order_by(JournalEntry.trade_date.desc(), JournalEntry.created_at.desc())).all()


def _similar_groups(entries: list[JournalEntry], max_distance: int) -> list[list[JournalEntry]]:
    by_day: dict[date, list[JournalEntry]] = defaultdict(list)
    for entry in entries:
        if entry.image_hash:
            by_day[entry.trade_date].append(entry)
    groups: list[list[JournalEntry]] = []
    for members in by_day.values():
        parent = list(range(len(members)))
        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for i, left in enumerate(members):
            a = int(left.image_hash, 16)
            for j in range(i + 1, len(members)):
                if (a ^ int(members[j].image_hash, 16)).bit_count() <= max_distance:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[rj] = ri
        buckets: dict[int, list[JournalEntry]] = defaultdict(list)
        for i, entry in enumerate(members):
            buckets[find(i)].append(entry)
        groups.extend(sorted(group, key=lambda e: e.created_at) for group in buckets.values() if len(group) > 1)
    return sorted(groups, key=lambda group: group[0].trade_date, reverse=True)


@journal_bp.get("/")
@login_required
def index():
    if not current_user.onboarding_complete:
        return redirect(url_for("journal.onboarding"))
    query_text = request.args.get("q", "").strip()[:100]
    date_filter = request.args.get("date", "").strip()
    statement = db.select(JournalEntry).where(JournalEntry.user_id == current_user.id, JournalEntry.deleted_at.is_(None))
    if query_text:
        like = f"%{query_text}%"
        statement = statement.where(or_(JournalEntry.symbol.ilike(like), JournalEntry.market.ilike(like), JournalEntry.reflection.ilike(like), JournalEntry.original_name.ilike(like)))
    if date_filter:
        try:
            statement = statement.where(JournalEntry.trade_date == date.fromisoformat(date_filter))
        except ValueError:
            date_filter = ""
    filtered = statement.subquery()
    total_count = db.session.scalar(db.select(func.count()).select_from(filtered)) or 0
    trading_day_count = db.session.scalar(db.select(func.count(func.distinct(filtered.c.trade_date)))) or 0
    page_size = 30
    try:
        current_page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        current_page = 1
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    current_page = min(current_page, total_pages)
    entries = db.session.scalars(statement.order_by(
        JournalEntry.trade_date.desc(), JournalEntry.created_at.desc()
    ).offset((current_page - 1) * page_size).limit(page_size)).all()
    page_start = (current_page - 1) * page_size + 1 if total_count else 0
    page_end = min(current_page * page_size, total_count)
    days: dict[date, list[JournalEntry]] = defaultdict(list)
    for entry in entries:
        days[entry.trade_date].append(entry)
    unread = current_user.notifications.filter_by(read_at=None).count()
    return render_template("index.html", entries=entries, days=days, query_text=query_text, date_filter=date_filter,
                           total_count=total_count, trading_day_count=trading_day_count, current_page=current_page,
                           total_pages=total_pages, has_prev=current_page > 1, has_next=current_page < total_pages,
                           page_start=page_start, page_end=page_end, unread=unread,
                           prompt=PROMPTS[datetime.now().timetuple().tm_yday % len(PROMPTS)])


@journal_bp.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    if request.method == "POST":
        current_user.onboarding_complete = True
        db.session.commit()
        return redirect(url_for("journal.index"))
    return render_template("onboarding.html")


@journal_bp.post("/capture")
@login_required
def capture():
    uploaded = request.files.get("screenshot")
    if not uploaded or not uploaded.filename:
        flash("Choose a screenshot to add to your journal.", "error")
        return redirect(url_for("journal.index"))
    data = uploaded.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        flash("That screenshot is larger than 16 MB.", "error")
        return redirect(url_for("journal.index"))
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format
            if image.width > 12000 or image.height > 12000:
                flash("That image is too large in dimensions. Try a smaller screenshot.", "error")
                return redirect(url_for("journal.index"))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        flash("Upload a valid PNG, JPEG or WebP screenshot.", "error")
        return redirect(url_for("journal.index"))
    if image_format not in ALLOWED_FORMATS:
        flash("Upload a PNG, JPEG or WebP screenshot.", "error")
        return redirect(url_for("journal.index"))
    try:
        trade_date = date.fromisoformat(request.form.get("trade_date", "") or date.today().isoformat())
    except ValueError:
        flash("Choose a valid trading day.", "error")
        return redirect(url_for("journal.index"))
    key = new_key(current_user.id, uploaded.filename)
    try:
        put_object(key, data, ALLOWED_FORMATS[image_format])
    except (StorageUnavailable, OSError, ValueError) as exc:
        current_app.logger.warning("Screenshot upload failed: %s", exc)
        flash("Screenshot storage is not ready. Configure durable storage before uploading.", "error")
        return redirect(url_for("journal.index"))
    entry = JournalEntry(
        user_id=current_user.id, storage_key=key, original_name=Path(uploaded.filename).name[:255],
        mime_type=ALLOWED_FORMATS[image_format], byte_size=len(data), image_hash=_average_hash(data),
        trade_date=trade_date, symbol=request.form.get("symbol", "").strip().upper()[:32],
        market=request.form.get("market", "").strip()[:80], reflection=request.form.get("reflection", "").strip()[:10000],
    )
    db.session.add(entry)
    if current_user.notify_journal:
        db.session.add(Notification(user_id=current_user.id, kind="journal", title="Screenshot saved", body="Your trading moment is in the journal."))
    db.session.commit()
    flash("Saved. Take a moment to add a note whenever you’re ready.", "success")
    return redirect(url_for("journal.entry", entry_id=entry.id))


@journal_bp.get("/entry/<int:entry_id>")
@login_required
def entry(entry_id: int):
    item = _owned(entry_id)
    return render_template("entry.html", entry=item, prompt=PROMPTS[(item.id - 1) % len(PROMPTS)])


@journal_bp.post("/entry/<int:entry_id>/update")
@login_required
def update_entry(entry_id: int):
    item = _owned(entry_id)
    data = request.get_json(silent=True) if request.is_json else request.form
    if not data:
        return jsonify(error="No changes were sent."), 400
    if "reflection" in data:
        item.reflection = str(data.get("reflection", ""))[:10000]
    if "symbol" in data:
        item.symbol = str(data.get("symbol", "")).strip().upper()[:32]
    if "market" in data:
        item.market = str(data.get("market", "")).strip()[:80]
    if "trade_date" in data:
        try:
            item.trade_date = date.fromisoformat(str(data["trade_date"]))
        except ValueError:
            return jsonify(error="Choose a valid trading day."), 400
    item.updated_at = utcnow()
    db.session.commit()
    if not request.is_json:
        flash("Details saved.", "success")
        return redirect(url_for("journal.entry", entry_id=item.id))
    return jsonify(saved=True, updated_at=item.updated_at.isoformat(timespec="seconds"))


@journal_bp.get("/media/<int:entry_id>")
@login_required
def media(entry_id: int):
    item = _owned(entry_id)
    try:
        external = get_object_url(item.storage_key)
        if external:
            return redirect(external, code=302)
        local_root = Path(current_app.config["LOCAL_UPLOAD_FOLDER"]).resolve()
        path = (local_root / item.storage_key).resolve()
        if local_root not in path.parents:
            abort(404)
        return send_from_directory(path.parent, path.name, mimetype=item.mime_type, as_attachment=False, max_age=0)
    except (StorageUnavailable, OSError) as exc:
        current_app.logger.warning("Screenshot read failed: %s", exc)
        abort(503)


@journal_bp.get("/entry/<int:entry_id>/download")
@login_required
def download_one(entry_id: int):
    item = _owned(entry_id)
    try:
        external = get_object_url(item.storage_key)
        if external:
            return redirect(external, code=302)
        return send_file(io.BytesIO(read_object(item.storage_key)), mimetype=item.mime_type, as_attachment=True, download_name=Path(item.original_name).name)
    except (StorageUnavailable, OSError) as exc:
        current_app.logger.warning("Screenshot download failed: %s", exc)
        abort(503)


@journal_bp.post("/downloads")
@login_required
def download_batch():
    raw_ids = request.form.getlist("entry_ids")
    ids = []
    for raw in raw_ids[:12]:
        try:
            ids.append(int(raw))
        except ValueError:
            continue
    entries = db.session.scalars(db.select(JournalEntry).where(
        JournalEntry.user_id == current_user.id, JournalEntry.deleted_at.is_(None), JournalEntry.id.in_(ids)
    )).all() if ids else []
    if not entries:
        flash("Select at least one screenshot to download.", "error")
        return redirect(url_for("journal.index"))
    if sum(item.byte_size for item in entries) > 64 * 1024 * 1024:
        flash("That batch is larger than 64 MB. Choose fewer screenshots and try again.", "error")
        return redirect(url_for("journal.index"))
    archive = io.BytesIO()
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for item in entries:
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(item.original_name).name) or f"screenshot-{item.id}.png"
                bundle.writestr(f"{item.trade_date.isoformat()}-{item.id}-{safe_name}", read_object(item.storage_key))
    except (StorageUnavailable, OSError) as exc:
        current_app.logger.warning("Screenshot archive failed: %s", exc)
        abort(503)
    archive.seek(0)
    return send_file(archive, mimetype="application/zip", as_attachment=True, download_name="tradevault-screenshots.zip")


@journal_bp.post("/entry/<int:entry_id>/delete")
@login_required
def delete_entry(entry_id: int):
    item = _owned(entry_id)
    item.deleted_at = utcnow()
    db.session.commit()
    flash("Removed from your journal. Stored file cleanup is not available through the runtime storage API.", "info")
    return redirect(url_for("journal.index"))


@journal_bp.get("/review")
@login_required
def review():
    entries = _today_entries()
    days: dict[date, list[JournalEntry]] = defaultdict(list)
    for item in entries:
        days[item.trade_date].append(item)
    similar = _similar_groups(entries, current_app.config["SIMILARITY_DISTANCE"])
    return render_template("review.html", days=days, similar=similar, count=len(entries), threshold=current_app.config["SIMILARITY_DISTANCE"])


@journal_bp.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    if request.method == "POST":
        current_user.notifications.filter_by(read_at=None).update({"read_at": utcnow()}, synchronize_session=False)
        db.session.commit()
        return jsonify(marked=True)
    items = current_user.notifications.order_by(Notification.created_at.desc()).limit(100).all()
    return render_template("notifications.html", notifications=items)


@journal_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        if request.form.get("section") == "notifications":
            current_user.notify_journal = request.form.get("notify_journal") == "on"
            current_user.notify_security = request.form.get("notify_security") == "on"
        else:
            current_user.display_name = request.form.get("display_name", "").strip()[:80]
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("journal.settings"))
    return render_template("settings.html")
