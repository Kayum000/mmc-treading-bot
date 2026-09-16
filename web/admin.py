"""Owner/admin control panel for MMC Trading Bot."""
from __future__ import annotations

import hmac
import os
import secrets
import time
from functools import wraps

import psycopg2
from flask import jsonify, redirect, render_template, request, session, url_for

from auth import _db_url, _hash_password, create_user, get_user, init_user_db


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


def _audit(actor_id, action, target_id=None, details=""):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO mmc_admin_audit(actor_user_id,action,target_user_id,details) VALUES (%s,%s,%s,%s)", (actor_id, action, target_id, details[:1000]))
        conn.commit()


def _memory_status():
    try:
        values = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0])
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", values.get("MemFree", 0))
        used = max(total - available, 0)
        return {"used_mb": round(used / 1024), "total_mb": round(total / 1024), "pct": round((used / total) * 100, 1) if total else 0}
    except Exception:
        return {"used_mb": 0, "total_mb": 0, "pct": 0}


def _load_status():
    try:
        return round(os.getloadavg()[0], 2)
    except Exception:
        return None


def _system_settings(cur):
    cur.execute("SELECT key,value FROM mmc_system_settings WHERE key IN ('maintenance_mode','maintenance_message')")
    data = {row[0]: row[1] for row in cur.fetchall()}
    return data.get("maintenance_mode", "off") == "on", data.get("maintenance_message", "")


def _dashboard_data():
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT u.id,u.username,u.email,u.role,u.active,u.created_at,u.last_login_at,
                          s.market_mode,s.pair,s.auto_signal,s.min_confidence,s.timezone,
                          COALESCE(p.signal_access,TRUE),COALESCE(p.auto_signal_access,TRUE),
                          COALESCE(p.real_market_access,TRUE),COALESCE(p.demo_market_access,TRUE),
                          COALESCE(p.advanced_settings_access,FALSE)
                          FROM mmc_users u LEFT JOIN mmc_user_settings s ON s.user_id=u.id
                          LEFT JOIN mmc_user_permissions p ON p.user_id=u.id ORDER BY u.id ASC""")
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
            maintenance_mode, maintenance_message = _system_settings(cur)
            cur.execute("SELECT id,action,actor_user_id,target_user_id,details,created_at FROM mmc_admin_audit ORDER BY id DESC LIMIT 30")
            audit_rows = cur.fetchall()
    users = []
    for row in rows:
        users.append({
            "id": int(row[0]), "username": row[1], "email": row[2] or "", "role": row[3],
            "active": bool(row[4]), "created_at": row[5], "last_login_at": row[6],
            "market_mode": row[7] or "", "pair": row[8] or "", "auto_signal": bool(row[9]),
            "min_confidence": float(row[10] or 0), "timezone": row[11] or "Asia/Dhaka",
            "signal_access": bool(row[12]), "auto_signal_access": bool(row[13]),
            "real_market_access": bool(row[14]), "demo_market_access": bool(row[15]),
            "advanced_settings_access": bool(row[16]),
        })
    audits = [{"id": r[0], "action": r[1], "actor": r[2], "target": r[3], "details": r[4] or "", "created_at": r[5]} for r in audit_rows]
    return users, total_users, active_users, inactive_users, admin_count, auto_signal_users, maintenance_mode, maintenance_message, audits


def init_admin_routes(app):
    init_user_db()

    @app.route("/admin", methods=["GET"])
    @_admin_required
    def admin_panel():
        users, total_users, active_users, inactive_users, admin_count, auto_signal_users, maintenance_mode, maintenance_message, audits = _dashboard_data()
        try:
            with _connect():
                db_status = "CONNECTED"
        except Exception:
            db_status = "ERROR"
        collector_hint = os.getenv("COLLECTOR_STATUS", "NOT REPORTED").upper()
        return render_template(
            "admin.html", users=users, total_users=total_users, active_users=active_users,
            inactive_users=inactive_users, admin_count=admin_count, auto_signal_users=auto_signal_users,
            current_user=get_user(session["user_id"]), csrf=session["admin_csrf"], db_status=db_status,
            app_env="configured" if os.getenv("DATABASE_URL") else "missing", memory=_memory_status(),
            load_avg=_load_status(), collector_status=collector_hint, signal_status="ROUTE AVAILABLE",
            maintenance_mode=maintenance_mode, maintenance_message=maintenance_message, audits=audits,
            server_time=int(time.time()),
        )

    @app.route("/admin/user/create", methods=["POST"])
    @_admin_required
    def admin_create_user():
        if not _csrf_ok():
            return jsonify({"ok": False, "error": "Invalid admin session token."}), 403
        try:
            user_id = create_user(request.form.get("username", ""), request.form.get("password", ""), request.form.get("email", ""), active=True)
            _audit(session["user_id"], "create_user", user_id, request.form.get("username", "").strip())
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return redirect(url_for("admin_panel"))

    @app.route("/admin/user/<int:user_id>", methods=["POST"])
    @_admin_required
    def admin_update_user(user_id):
        if not _csrf_ok():
            return jsonify({"ok": False, "error": "Invalid admin session token."}), 403
        action = request.form.get("action", "").strip().lower()
        actor_id = int(session.get("user_id"))
        if user_id == actor_id and action in {"deactivate", "delete"}:
            return jsonify({"ok": False, "error": "You cannot disable or delete your own owner account."}), 400
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id,role FROM mmc_users WHERE id=%s", (user_id,))
                row = cur.fetchone()
                if not row:
                    return jsonify({"ok": False, "error": "User not found."}), 404
                if row[1] == "owner":
                    return jsonify({"ok": False, "error": "Owner account is protected."}), 400
                if action == "save_settings":
                    cur.execute("""INSERT INTO mmc_user_settings(user_id,market_mode,pair,auto_signal,min_confidence,timezone)
                        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET market_mode=EXCLUDED.market_mode,
                        pair=EXCLUDED.pair,auto_signal=EXCLUDED.auto_signal,min_confidence=EXCLUDED.min_confidence,
                        timezone=EXCLUDED.timezone,updated_at=NOW()""", (user_id, request.form.get("market_mode", "real"), request.form.get("pair", ""), request.form.get("auto_signal") == "on", float(request.form.get("min_confidence", "0") or 0), request.form.get("timezone", "Asia/Dhaka")))
                    cur.execute("""INSERT INTO mmc_user_permissions(user_id,signal_access,auto_signal_access,real_market_access,demo_market_access,advanced_settings_access)
                        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET signal_access=EXCLUDED.signal_access,
                        auto_signal_access=EXCLUDED.auto_signal_access,real_market_access=EXCLUDED.real_market_access,
                        demo_market_access=EXCLUDED.demo_market_access,advanced_settings_access=EXCLUDED.advanced_settings_access,updated_at=NOW()""",
                        (user_id, request.form.get("signal_access") == "on", request.form.get("auto_signal_access") == "on", request.form.get("real_market_access") == "on", request.form.get("demo_market_access") == "on", request.form.get("advanced_settings_access") == "on"))
                    action = "save_user_access"
                elif action == "activate":
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
        _audit(actor_id, action, user_id)
        return redirect(url_for("admin_panel"))

    @app.route("/admin/system", methods=["POST"])
    @_admin_required
    def admin_system_control():
        if not _csrf_ok():
            return jsonify({"ok": False, "error": "Invalid admin session token."}), 403
        actor = get_user(int(session["user_id"]))
        if not actor or actor.get("role") != "owner":
            return jsonify({"ok": False, "error": "Owner permission required."}), 403
        if request.form.get("action", "") != "maintenance":
            return jsonify({"ok": False, "error": "Unsupported system action."}), 400
        enabled = request.form.get("enabled") == "on"
        message = request.form.get("message", "").strip()[:500]
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO mmc_system_settings(key,value) VALUES ('maintenance_mode',%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()", ("on" if enabled else "off",))
                cur.execute("INSERT INTO mmc_system_settings(key,value) VALUES ('maintenance_message',%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()", (message,))
            conn.commit()
        _audit(session["user_id"], "maintenance_on" if enabled else "maintenance_off", None, message)
        return redirect(url_for("admin_panel"))
