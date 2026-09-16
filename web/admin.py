"""Owner/admin control panel for MMC Trading Bot.

This module is intentionally isolated from the main dashboard so the existing
signal UI remains unchanged. All mutating actions require an authenticated
admin session and a per-session CSRF token.
"""
from __future__ import annotations

import hmac
import os
import secrets
from functools import wraps

import psycopg2
from flask import jsonify, redirect, render_template, request, session, url_for

from auth import _db_url, _hash_password, get_user


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


def init_admin_routes(app):
    @app.route("/admin", methods=["GET"])
    @_admin_required
    def admin_panel():
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT u.id,u.username,u.email,u.role,u.active,u.created_at,u.last_login_at,
                              s.market_mode,s.pair,s.auto_signal
                              FROM mmc_users u LEFT JOIN mmc_user_settings s ON s.user_id=u.id
                              ORDER BY u.id ASC""")
                rows = cur.fetchall()
                cur.execute("SELECT COUNT(*) FROM mmc_users")
                total_users = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM mmc_users WHERE active")
                active_users = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM mmc_users WHERE role IN ('admin','owner')")
                admin_count = int(cur.fetchone()[0])
        users = []
        for row in rows:
            users.append({
                "id": int(row[0]), "username": row[1], "email": row[2] or "", "role": row[3],
                "active": bool(row[4]), "created_at": row[5], "last_login_at": row[6],
                "market_mode": row[7] or "", "pair": row[8] or "", "auto_signal": bool(row[9]),
            })
        return render_template("admin.html", users=users, total_users=total_users,
                               active_users=active_users, admin_count=admin_count,
                               current_user=get_user(session["user_id"]), csrf=session["admin_csrf"])

    @app.route("/admin/user/<int:user_id>", methods=["POST"])
    @_admin_required
    def admin_update_user(user_id):
        if not _csrf_ok():
            return jsonify({"ok": False, "error": "Invalid admin session token."}), 403
        action = request.form.get("action", "").strip().lower()
        if user_id == int(session.get("user_id")) and action in {"deactivate", "delete"}:
            return jsonify({"ok": False, "error": "You cannot disable or delete your own owner account."}), 400
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id,role FROM mmc_users WHERE id=%s", (user_id,))
                row = cur.fetchone()
                if not row:
                    return jsonify({"ok": False, "error": "User not found."}), 404
                if row[1] == "owner" and action != "promote_owner":
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
