"""Private unified Admin App.

The Admin App reuses the existing Signal System and the existing Admin Panel
inside one browser window. No signal-generation logic is duplicated.
"""
from __future__ import annotations

from flask import redirect, render_template, session, url_for

from auth import get_user


def init_admin_app_routes(app):
    @app.route("/admin-app", methods=["GET"])
    def admin_app():
        uid = session.get("user_id")
        user = get_user(uid) if uid else None
        # The private Admin App is for the owner account only.
        if not user or user.get("role") != "owner":
            return redirect(url_for("login"))
        return render_template("admin_app.html", user=user)
