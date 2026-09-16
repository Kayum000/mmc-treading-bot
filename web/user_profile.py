"""User-owned profile and identity verification.

The existing file/format/size pre-check remains intact. A separate,
provider-backed identity verification step can now validate NID data and
compare the selfie with the identity-document face. No provider is assumed:
without explicit configuration the result stays pending/manual review.
"""
from __future__ import annotations

import datetime as dt
import hmac
import json
import os

import psycopg2
import requests
from flask import Response, jsonify, redirect, render_template, request, session, url_for

from auth import _db_url, get_user, init_user_db

MAX_IMAGE_BYTES = 3 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
VERIFICATION_PROVIDER_URL = os.getenv("IDENTITY_VERIFICATION_URL", "").strip()
VERIFICATION_PROVIDER_TOKEN = os.getenv("IDENTITY_VERIFICATION_TOKEN", "").strip()


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
                nid_status VARCHAR(32) NOT NULL DEFAULT 'not_submitted',
                selfie_status VARCHAR(32) NOT NULL DEFAULT 'not_submitted',
                auto_check_status VARCHAR(32) NOT NULL DEFAULT 'not_checked',
                auto_check_note TEXT,
                identity_status VARCHAR(32) NOT NULL DEFAULT 'not_checked',
                face_match_status VARCHAR(32) NOT NULL DEFAULT 'not_checked',
                identity_note TEXT,
                verification_provider VARCHAR(128),
                reviewed_by BIGINT REFERENCES mmc_users(id) ON DELETE SET NULL,
                reviewed_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            # Safe additive migration for installations created by the earlier version.
            for name, definition in (
                ("identity_status", "VARCHAR(32) NOT NULL DEFAULT 'not_checked'"),
                ("face_match_status", "VARCHAR(32) NOT NULL DEFAULT 'not_checked'"),
                ("identity_note", "TEXT"),
                ("verification_provider", "VARCHAR(128)"),
            ):
                cur.execute(f"ALTER TABLE mmc_user_verification ADD COLUMN IF NOT EXISTS {name} {definition}")
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
    good = (data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n") or (data.startswith(b"RIFF") and b"WEBP" in data[:16]))
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
    return "passed_precheck", "All three images passed file/format/size pre-check."


def _run_identity_verification(front, back, selfie):
    """Run the separate real-verification provider, if explicitly configured.

    The provider is expected to accept multipart fields `nid_front`,
    `nid_back`, and `selfie`, and return JSON with `identity_status` and
    `face_match_status`. Accepted successful values are `verified`, while
    `rejected` is a definitive provider rejection. Any timeout/error remains
    pending/manual review and never auto-approves a user.
    """
    if not VERIFICATION_PROVIDER_URL:
        return "not_configured", "not_checked", "No identity verification provider configured; manual review required.", "none"
    files = {
        "nid_front": ("nid_front", front, "application/octet-stream"),
        "nid_back": ("nid_back", back, "application/octet-stream"),
        "selfie": ("selfie", selfie, "application/octet-stream"),
    }
    headers = {"Accept": "application/json"}
    if VERIFICATION_PROVIDER_TOKEN:
        headers["Authorization"] = f"Bearer {VERIFICATION_PROVIDER_TOKEN}"
    try:
        response = requests.post(VERIFICATION_PROVIDER_URL, files=files, headers=headers, timeout=(5, 30))
        if not response.ok:
            return "pending_manual", "pending_manual", f"Verification provider HTTP {response.status_code}; manual review required.", "configured"
        payload = response.json()
        identity = str(payload.get("identity_status", "pending_manual")).lower()
        face = str(payload.get("face_match_status", "pending_manual")).lower()
        allowed = {"verified", "rejected", "pending_manual", "not_checked"}
        if identity not in allowed:
            identity = "pending_manual"
        if face not in allowed:
            face = "pending_manual"
        note = str(payload.get("note", "Provider verification completed."))[:1000]
        return identity, face, note, str(payload.get("provider", "configured"))[:128]
    except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError) as exc:
        return "pending_manual", "pending_manual", f"Verification provider unavailable ({type(exc).__name__}); manual review required.", "configured"


def _verification_row(user_id):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT nid_status,selfie_status,auto_check_status,auto_check_note,
                          profile_pic IS NOT NULL,nid_front IS NOT NULL,nid_back IS NOT NULL,selfie IS NOT NULL,
                          reviewed_at,identity_status,face_match_status,identity_note,verification_provider
                          FROM mmc_user_verification WHERE user_id=%s""", (user_id,))
            row = cur.fetchone()
    if not row:
        return {"nid_status": "not_submitted", "selfie_status": "not_submitted", "auto_check_status": "not_checked", "auto_check_note": "", "has_profile": False, "has_front": False, "has_back": False, "has_selfie": False, "reviewed_at": None, "identity_status": "not_checked", "face_match_status": "not_checked", "identity_note": "", "verification_provider": "none"}
    return {"nid_status": row[0], "selfie_status": row[1], "auto_check_status": row[2], "auto_check_note": row[3] or "", "has_profile": bool(row[4]), "has_front": bool(row[5]), "has_back": bool(row[6]), "has_selfie": bool(row[7]), "reviewed_at": row[8], "identity_status": row[9] or "not_checked", "face_match_status": row[10] or "not_checked", "identity_note": row[11] or "", "verification_provider": row[12] or "none"}


def _process_verification(uid):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nid_front,nid_back,selfie FROM mmc_user_verification WHERE user_id=%s", (uid,))
            row = cur.fetchone()
            if not row:
                return
            pre_status, pre_note = _auto_check(row[0], row[1], row[2])
            identity = "not_checked"
            face = "not_checked"
            identity_note = ""
            provider = "none"
            if pre_status == "passed_precheck":
                identity, face, identity_note, provider = _run_identity_verification(row[0], row[1], row[2])
            cur.execute("""UPDATE mmc_user_verification SET
                auto_check_status=%s, auto_check_note=%s,
                identity_status=%s, face_match_status=%s, identity_note=%s,
                verification_provider=%s, updated_at=NOW() WHERE user_id=%s""",
                (pre_status, pre_note, identity, face, identity_note, provider, uid))
            conn.commit()


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
                if kind in {"nid_front", "nid_back"}:
                    cur.execute("UPDATE mmc_user_verification SET nid_status='pending_review',auto_check_status='not_checked',identity_status='not_checked',face_match_status='not_checked',updated_at=NOW() WHERE user_id=%s", (uid,))
                elif kind == "selfie":
                    cur.execute("UPDATE mmc_user_verification SET selfie_status='pending_review',auto_check_status='not_checked',identity_status='not_checked',face_match_status='not_checked',updated_at=NOW() WHERE user_id=%s", (uid,))
            conn.commit()
        if kind in {"nid_front", "nid_back", "selfie"}:
            _process_verification(uid)
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
        return Response(bytes(row[0]), mimetype=row[1] or "image/jpeg", headers={"Cache-Control": "private, max-age=60"})

    @app.route("/profile/verification/recheck", methods=["POST"])
    def profile_recheck():
        uid = _uid()
        if not uid or not get_user(uid):
            return jsonify({"ok": False, "error": "Login required."}), 401
        if not _csrf_ok():
            return jsonify({"ok": False, "error": "Invalid profile session token."}), 403
        _process_verification(uid)
        return redirect(url_for("user_profile"))

    @app.after_request
    def inject_user_profile_navigation(response):
        if not (response.content_type or "").startswith("text/html"):
            return response
        html = response.get_data(as_text=True)
        if "USER_PROFILE_NAV" in html or "/profile" in request.path:
            return response
        if 'data-action="settings"' not in html and 'class="avatar"' not in html:
            return response
        script = """<script id=\"USER_PROFILE_NAV\">(()=>{const go=()=>{window.location.assign('/profile')};const settings=document.querySelector('[data-action=\"settings\"]');if(settings){settings.addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();go()},true);settings.setAttribute('aria-label','My Profile')}const avatar=document.querySelector('.avatar');if(avatar){avatar.style.cursor='pointer';avatar.setAttribute('role','link');avatar.setAttribute('tabindex','0');avatar.setAttribute('title','Open My Profile');avatar.addEventListener('click',e=>{e.preventDefault();go()},true);avatar.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}},true)}})();</script>"""
        if "</body>" in html:
            response.set_data(html.replace("</body>", script + "</body>", 1))
        return response
