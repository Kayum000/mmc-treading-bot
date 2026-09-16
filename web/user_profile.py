"""User-owned profile and identity verification UI.

Profile editing belongs to the signed-in user, not the owner admin panel.
Images are stored in a dedicated Postgres table so camera/gallery uploads do
not depend on an ephemeral Render filesystem.
"""
from __future__ import annotations

import base64
import datetime as dt
import hmac
import os

import psycopg2
from flask import jsonify, redirect, render_template, request, session, url_for

from auth import _db_url, get_user, init_user_db

MAX_IMAGE_BYTES = 3 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _connect():
    return psycopg2.connect(_db_url(), connect_timeout=8)


def _uid():
    try:
        return int(session.get("user_id"))
    except (TypeError, ValueError):
        return None


def _csrf_token():
    token = session.get("profile_csrf")
    if not token:
        token = os.urandom(24).hex()
        session["profile_csrf"] = token
    return token


def _csrf_ok():
    expected = session.get("profile_csrf", "")
    supplied = request.form.get("csrf", "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _init_tables():
    init_user_db()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS mmc_user_verification (
                user_id BIGINT PRIMARY KEY REFERENCES mmc_users(id) ON DELETE CASCADE,
                profile_pic BYTEA, profile_pic_mime VARCHAR(64),
                nid_front BYTEA, nid_front_mime VARCHAR(64),
                nid_back BYTEA, nid_back_mime VARCHAR(64),
                selfie BYTEA, selfie_mime VARCHAR(64),
                nid_status VARCHAR(24) NOT NULL DEFAULT 'not_submitted',
                selfie_status VARCHAR(24) NOT NULL DEFAULT 'not_submitted',
                auto_check_status VARCHAR(24) NOT NULL DEFAULT 'not_checked',
                auto_check_note TEXT,
                reviewed_by BIGINT REFERENCES mmc_users(id) ON DELETE SET NULL,
                reviewed_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
        conn.commit()


def _valid_image(upload):
    if not upload or not upload.filename:
        return None, None, "ছবি নির্বাচন করা হয়নি।"
    if upload.mimetype not in ALLOWED_TYPES:
        return None, None, "শুধু JPG, PNG বা WEBP ছবি দেওয়া যাবে।"
    data = upload.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        return None, None, "প্রতিটি ছবি সর্বোচ্চ 3 MB হতে পারবে।"
    if not data:
        return None, None, "ছবিটি খালি।"
    # Lightweight magic-byte check prevents simply renaming another file to .jpg.
    good = (data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"RIFF") and b"WEBP" in data[:16])
    if not good:
        return None, None, "ছবির ফরম্যাট যাচাই করা যায়নি।"
    return data, upload.mimetype, None


def _auto_check(front, back, selfie):
    missing = []
    if not front:
        missing.append("NID front")
    if not back:
        missing.append("NID back")
    if not selfie:
        missing.append("selfie")
    if missing:
        return "needs_action", "Missing: " + ", ".join(missing)
    if min(len(front), len(back), len(selfie)) < 12 * 1024:
        return "needs_review", "Images are unusually small; manual review required."
    return "passed_precheck", "All three images passed file/format/size pre-check. Human/admin identity review is still required."


def _verification_row(user_id):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT nid_status,selfie_status,auto_check_status,auto_check_note,
                          profile_pic IS NOT NULL,nid_front IS NOT NULL,nid_back IS NOT NULL,selfie IS NOT NULL,
                          reviewed_at FROM mmc_user_verification WHERE user_id=%s""", (user_id,))
            row = cur.fetchone()
    if not row:
        return {"nid_status": "not_submitted", "selfie_status": "not_submitted", "auto_check_status": "not_checked", "auto_check_note": "", "has_profile": False, "has_front": False, "has_back": False, "has_selfie": False, "reviewed_at": None}
    return {"nid_status": row[0], "selfie_status": row[1], "auto_check_status": row[2], "auto_check_note": row[3] or "", "has_profile": bool(row[4]), "has_front": bool(row[5]), "has_back": bool(row[6]), "has_selfie": bool(row[7]), "reviewed_at": row[8]}


def init_user_profile_routes(app):
    _init_tables()

    @app.route("/profile", methods=["GET", "POST"])
    def user_profile():
        uid = _uid()
        user = get_user(uid) if uid else None
        if not user:
            return redirect(url_for("login"))
        if request.method == "POST":
            if not _csrf_ok():
                return jsonify({"ok": False, "error": "Invalid profile session token."}), 403
            full_name = request.form.get("full_name", "").strip()[:160]
            email = request.form.get("email", "").strip().lower()[:255] or None
            phone = request.form.get("phone", "").strip()[:32]
            dob = request.form.get("date_of_birth", "").strip() or None
            telegram = request.form.get("telegram", "").strip()[:128]
            try:
                parsed_dob = dt.date.fromisoformat(dob) if dob else None
                if parsed_dob and parsed_dob > dt.date.today():
                    raise ValueError("Date of birth cannot be in the future.")
                with _connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE mmc_users SET full_name=%s,email=%s,phone=%s,date_of_birth=%s,telegram=%s WHERE id=%s", (full_name, email, phone, parsed_dob, telegram, uid))
                    conn.commit()
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400
            return redirect(url_for("user_profile"))
        return render_template("profile.html", user=user, verification=_verification_row(uid), csrf=_csrf_token())

    @app.route("/profile/upload", methods=["POST"])
    def profile_upload():
        uid = _uid()
        if not uid or not get_user(uid):
            return jsonify({"ok": False, "error": "Login required."}), 401
        if not _csrf_ok():
            return jsonify({"ok": False, "error": "Invalid profile session token."}), 403
        kind = request.form.get("kind", "")
        field = {"profile": "profile_pic", "nid_front": "nid_front", "nid_back": "nid_back", "selfie": "selfie"}.get(kind)
        if not field:
            return jsonify({"ok": False, "error": "Invalid upload type."}), 400
        data, mime, error = _valid_image(request.files.get("image"))
        if error:
            return jsonify({"ok": False, "error": error}), 400
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO mmc_user_verification(user_id) VALUES (%s) ON CONFLICT(user_id) DO NOTHING", (uid,))
                cur.execute(f"UPDATE mmc_user_verification SET {field}=%s,{field}_mime=%s,updated_at=NOW() WHERE user_id=%s", (psycopg2.Binary(data), mime, uid))
                if kind == "nid_front" or kind == "nid_back":
                    cur.execute("UPDATE mmc_user_verification SET nid_status='pending_review',auto_check_status='not_checked',updated_at=NOW() WHERE user_id=%s", (uid,))
                elif kind == "selfie":
                    cur.execute("UPDATE mmc_user_verification SET selfie_status='pending_review',auto_check_status='not_checked',updated_at=NOW() WHERE user_id=%s", (uid,))
            conn.commit()
        if kind in {"nid_front", "nid_back", "selfie"}:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT nid_front,nid_back,selfie FROM mmc_user_verification WHERE user_id=%s", (uid,))
                    row = cur.fetchone()
                    status, note = _auto_check(row[0], row[1], row[2])
                    cur.execute("UPDATE mmc_user_verification SET auto_check_status=%s,auto_check_note=%s,updated_at=NOW() WHERE user_id=%s", (status, note, uid))
                conn.commit()
        return redirect(url_for("user_profile"))

    @app.route("/profile/image/<kind>", methods=["GET"])
    def profile_image(kind):
        uid = _uid()
        if not uid or not get_user(uid):
            return jsonify({"ok": False, "error": "Login required."}), 401
        field = {"profile": "profile_pic", "nid_front": "nid_front", "nid_back": "nid_back", "selfie": "selfie"}.get(kind)
        if not field:
            return jsonify({"ok": False, "error": "Invalid image."}), 400
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {field},{field}_mime FROM mmc_user_verification WHERE user_id=%s", (uid,))
                row = cur.fetchone()
        if not row or not row[0]:
            return ("", 404)
        from flask import Response
        return Response(bytes(row[0]), mimetype=row[1] or "image/jpeg", headers={"Cache-Control": "private, max-age=60"})

    @app.route("/profile/verification/recheck", methods=["POST"])
    def profile_recheck():
        uid = _uid()
        if not uid or not get_user(uid):
            return jsonify({"ok": False, "error": "Login required."}), 401
        if not _csrf_ok():
            return jsonify({"ok": False, "error": "Invalid profile session token."}), 403
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT nid_front,nid_back,selfie FROM mmc_user_verification WHERE user_id=%s", (uid,))
                row = cur.fetchone()
                if not row:
                    return redirect(url_for("user_profile"))
                status, note = _auto_check(row[0], row[1], row[2])
                cur.execute("UPDATE mmc_user_verification SET auto_check_status=%s,auto_check_note=%s,updated_at=NOW() WHERE user_id=%s", (status, note, uid))
            conn.commit()
        return redirect(url_for("user_profile"))
