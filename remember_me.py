"""Persistent login support for the web login page.

Uses Flask's signed session cookie instead of storing the user's password.
The existing authentication check and credentials remain unchanged.
"""
from datetime import timedelta
import hmac
import os

from flask import redirect, render_template, request, session, url_for


def init_remember_me(app):
    """Add a persistent Remember Me option without changing app auth logic."""
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(days=365))

    def login_with_remember():
        if session.get("authenticated"):
            return redirect(url_for("index"))

        error = None
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            remember = request.form.get("remember_me") == "1"
            auth_username = os.getenv("APP_USERNAME", "admin")
            auth_password = os.getenv("APP_PASSWORD", "")

            if not auth_password:
                error = "Login is not configured yet. Set APP_PASSWORD in the server environment."
            elif hmac.compare_digest(username, auth_username) and hmac.compare_digest(password, auth_password):
                session.clear()
                session.permanent = remember
                session["authenticated"] = True
                return redirect(url_for("index"))
            else:
                error = "Invalid username or password."

        return render_template("login.html", error=error)

    # Keep the existing endpoint name/route; only replace its view function.
    app.view_functions["login"] = login_with_remember
