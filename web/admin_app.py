"""Private Admin App shell.

The Admin App intentionally reuses the exact existing signal dashboard in an
embedded frame, so signal-generation logic is not duplicated or changed.
Only admin/owner users can open this shell, and it provides the extra Admin
Panel entry point alongside the full signal system.
"""
from __future__ import annotations

from functools import wraps

from flask import redirect, render_template, session, url_for

from auth import get_user


def init_admin_app_routes(app):
    @app.route("/admin-app", methods=["GET"])
    def admin_app():
        uid = session.get("user_id")
        user = get_user(uid) if uid else None
        if not user or user.get("role") not in {"admin", "owner"}:
            return redirect(url_for("login"))
        return render_template("admin_app.html", user=user)
