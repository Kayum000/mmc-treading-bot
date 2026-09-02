"""On-demand web UI for Real Forex and Crypto MMC signals."""
from __future__ import annotations

import hmac
import os
import time
from flask import Flask, render_template, request, redirect, url_for, session

from signals.get_signal import get_signal
from data.twelve_data_forex import fetch_api_usage, get_credit_usage

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY") or os.urandom(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "1") == "1",
)
AUTH_USERNAME = os.getenv("APP_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("APP_PASSWORD", "")

REAL_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "GBP/CHF",
    "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY", "EUR/AUD", "GBP/AUD",
    "AUD/CAD", "NZD/CAD",
]
CRYPTO_PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "LTC/USDT",
]

_USAGE_CACHE = {"data": None, "at": 0.0}


def _find_number(obj, names):
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_norm = str(key).lower().replace("-", "_")
            if key_norm in names and isinstance(value, (int, float)):
                return int(value)
        for value in obj.values():
            found = _find_number(value, names)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_number(value, names)
            if found is not None:
                return found
    return None


def _usage_view():
    """Use real Twelve Data usage, cached for 60 seconds."""
    now = time.time()
    if now - _USAGE_CACHE["at"] >= 60 or _USAGE_CACHE["data"] is None:
        try:
            _USAGE_CACHE["data"] = fetch_api_usage()
            _USAGE_CACHE["at"] = now
        except Exception:
            pass

    payload = _USAGE_CACHE["data"]
    daily_left = None
    daily_limit = None
    if payload:
        daily_left = _find_number(payload, {"daily_credits_left", "daily_left", "daily_remaining", "credits_left"})
        daily_limit = _find_number(payload, {"daily_credits", "daily_limit", "daily_quota"})

    minute = get_credit_usage()
    return {
        "daily_left": daily_left,
        "daily_limit": daily_limit or (800 if daily_left is not None else None),
        "minute_left": minute.get("left"),
        "minute_limit": minute.get("limit"),
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not AUTH_PASSWORD:
            error = "Login is not configured yet. Set APP_PASSWORD in the server environment."
        elif hmac.compare_digest(username, AUTH_USERNAME) and hmac.compare_digest(password, AUTH_PASSWORD):
            session.clear()
            session["authenticated"] = True
            return redirect(url_for("index"))
        else:
            error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout", methods=["GET"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="sk_bot_logo.svg"))


@app.route("/privacy")
def privacy():
    """Public privacy policy page for app-store review and users."""
    return render_template("privacy.html")


@app.before_request
def require_login():
    if request.endpoint in {"login", "favicon", "privacy", "static"}:
        return None
    if not session.get("authenticated"):
        return redirect(url_for("login"))
    return None


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    if request.method == "POST":
        mode = request.form.get("mode", "").strip().lower()
        pair = request.form.get("pair", "").strip().upper()
    else:
        # Restore the last market selected by this logged-in user.
        mode = session.get("selected_mode", "")
        pair = session.get("selected_pair", "")

    if mode not in {"real", "crypto"}:
        mode = ""
        pair = ""

    pairs = REAL_PAIRS if mode == "real" else CRYPTO_PAIRS if mode == "crypto" else []

    if pair not in pairs:
        pair = ""

    if request.method == "POST":
        if not pair:
            error = "Please select a market before GET SIGNAL."
        else:
            # Save exactly the market the user chose. It stays selected after
            # GET SIGNAL and on the next page load until the user changes it.
            session["selected_mode"] = mode
            session["selected_pair"] = pair
            try:
                result = get_signal(pair, mode)
            except Exception as exc:
                error = str(exc)

    usage = _usage_view()
    return render_template(
        "index.html",
        real_pairs=REAL_PAIRS,
        crypto_pairs=CRYPTO_PAIRS,
        mode=mode,
        pair=pair,
        result=result,
        error=error,
        usage=usage,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
