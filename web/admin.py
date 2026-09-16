"""Owner/admin control panel for MMC Trading Bot."""
from __future__ import annotations

import hmac
import os
import secrets
from functools import wraps

import psycopg2
from flask import jsonify, redirect, render_template, request, session, url_for

from auth import _db_url, _hash_password, create_user, get_settings, get_user, save_settings


def _connect():
    return psycopg2.connect(_db_url(), connect_timeout=8)


def _admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        uid = session.get("user_id")
        user = get_user(uid) if uid else None
        if not user or user.get("role") not in {"admin", "owner"}:
            return redirect(url_for("login"))
        if "admin_csrf" not in session:
            session["admin_csrf"] = secrets.token_urlsafe(32)
        return view(*args, **kwargs)
    return wrapped


def _csrf_ok():
    expected = session.get("admin_csrf", "")
    supplied = request.form.get("csrf", "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _dashboard_data():
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT u.id,u.username,u.email,u.role,u.active,u.created_at,u.last_login_at,
                          s.market_mode,s.pair,s.auto_signal,s.min_confidence,s.timezone
                          FROM mmc_users u LEFT JOIN mmc_user_settings s ON s.user_id=u.id
                          ORDER BY u.id ASC""")
            rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) FROM mmc_users")
            total_users = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM mmc_users WHERE active")
            active_users = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM mmc_users WHERE NOT active")
            inactive_users = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM mmc_users WHERE role IN ('admin','owner')")
            admin_count = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM mmc_user_settings WHERE auto_signal")
            auto_signal_users = int(cur.fetchone()[0])
    users = []
    for row in rows:
        users.append({
            "id": int(row[0]), "username": row[1], "email": row[2] or "", "role": row[3],
            "active": bool(row[4]), "created_at": row[5], "last_login_at": row[6],
            "market_mode": row[7] or "", "pair": row[8] or "", "auto_signal": bool(row[9]),
            "min_confidence": float(row[10] or 0), "timezone": row[11] or "Asia/Dhaka",
        })
    return users, total_users, active_users, inactive_users, admin_count, auto_signal_users


def init_admin_routes(app):
    @app.route("/admin", methods=["GET"])
    @_admin_required
    def admin_panel():
        users, total_users, active_users, inactive_users, admin_count, auto_signal_users = _dashboard_data()
        try:
            with _connect():
                db_status = "CONNECTED"
        except Exception:
            db_status = "ERROR"
        return render_template(
            "admin.html", users=users, total_users=total_users, active_users=active_users,
            inactive_users=inactive_users, admin_count=admin_count, auto_signal_users=auto_signal_users,
            current_user=get_user(session["user_id"]), csrf=session["admin_csrf"],
            db_status=db_status, signal_status="ONLINE", app_env="configured" if os.getenv("DATABASE_URL") else "missing",
        )

    @app.route("/admin/user/create", methods=["POST"])
    @_admin_required
    def admin_create_user():
        if not _csrf_ok():
            return jsonify({"ok": False, "error": "Invalid admin session token."}), 403
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        try:
            user_id = create_user(username, password, email)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return redirect(url_for("admin_panel"))

    @app.route("/admin/user/<int:user_id>", methods=["POST"])
    @_admin_required
    def admin_update_user(user_id):
        if not _csrf_ok():
            return jsonify({"ok": False, "error": "Invalid admin session token."}), 403
        action = request.form.get("action", "").strip().lower()
        if user_id == int(session.get("user_id")) and action in {"deactivate", "delete"}:
            return jsonify({"ok": False, "error": "You cannot disable or delete your own owner account."}), 400
        if action == "save_settings":
            try:
                save_settings(
                    user_id, request.form.get("market_mode", "real"), request.form.get("pair", ""),
                    request.form.get("auto_signal") == "on", float(request.form.get("min_confidence", "0") or 0),
                    request.form.get("timezone", "Asia/Dhaka"),
                )
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400
            return redirect(url_for("admin_panel"))
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id,role FROM mmc_users WHERE id=%s", (user_id,))
                row = cur.fetchone()
                if not row:
                    return jsonify({"ok": False, "error": "User not found."}), 404
                if row[1] == "owner":
                    return jsonify({"ok": False, "error": "Owner account is protected."}), 400
                if action == "activate":
                    cur.execute("UPDATE mmc_users SET active=TRUE WHERE id=%s", (user_id,))
                elif action == "deactivate":
                    cur.execute("UPDATE mmc_users SET active=FALSE WHERE id=%s", (user_id,))
                elif action == "make_admin":
                    cur.execute("UPDATE mmc_users SET role='admin',active=TRUE WHERE id=%s", (user_id,))
                elif action == "make_user":
                    cur.execute("UPDATE mmc_users SET role='user' WHERE id=%s", (user_id,))
                elif action == "reset_password":
                    password = request.form.get("password", "")
                    if len(password) < 8:
                        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
                    cur.execute("UPDATE mmc_users SET password_hash=%s,active=TRUE WHERE id=%s", (_hash_password(password), user_id))
                elif action == "delete":
                    cur.execute("DELETE FROM mmc_users WHERE id=%s", (user_id,))
                else:
                    return jsonify({"ok": False, "error": "Unsupported action."}), 400
            conn.commit()
        return redirect(url_for("admin_panel"))
