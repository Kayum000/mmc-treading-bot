"""Web UI for Real Forex and Quotex OTC signal generation."""
from __future__ import annotations

import hmac
import os
import time
from flask import Flask, jsonify, render_template, request, redirect, url_for, session

from signals.get_signal import get_signal
from performance import record_signal, get_performance, clear_performance_history
from data.biquote_forex import fetch_api_usage, get_credit_usage
from data.news_direction import get_news_direction_for_pair
from data.news_events import get_weekly_news_events_for_pair
from data.all_news_events import get_all_news_events
from data.otc_markets import OTC_DISPLAY_PAIRS

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY") or os.getenv("MASTER_SETUP_KEY") or os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "1") == "1")
AUTH_USERNAME = os.getenv("APP_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("APP_PASSWORD", "")

REAL_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "GBP/CHF",
    "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY", "EUR/AUD", "GBP/AUD",
    "AUD/CAD", "NZD/CAD",
]
# Keep the dashboard, validation endpoint, signal layer and collectors on the
# same canonical OTC registry. Do not maintain a second hard-coded OTC list here.
QUOTEX_OTC_PAIRS = list(OTC_DISPLAY_PAIRS)
_USAGE_CACHE = {"data": None, "at": 0.0}


def _valid_pairs(mode: str):
    return REAL_PAIRS if mode == "real" else QUOTEX_OTC_PAIRS if mode == "quotex_otc" else []


def _usage_view():
    now = time.time()
    if now - _USAGE_CACHE["at"] >= 60 or _USAGE_CACHE["data"] is None:
        try:
            _USAGE_CACHE["data"] = fetch_api_usage()
            _USAGE_CACHE["at"] = now
        except Exception:
            pass
    minute = get_credit_usage()
    return {"daily_left": None, "daily_limit": None, "minute_left": minute.get("left"), "minute_limit": minute.get("limit")}


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
            session.clear(); session["authenticated"] = True; return redirect(url_for("index"))
        else:
            error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout", methods=["GET"])
def logout():
    session.clear(); return redirect(url_for("login"))


@app.route("/favicon.ico")
def favicon(): return redirect(url_for("static", filename="sk_bot_logo.svg"))


@app.route("/privacy")
def privacy(): return render_template("privacy.html")


def _collector_request_authenticated() -> bool:
    """Allow the private candle collector through the dashboard login gate."""
    if request.endpoint != "quotex_ingest":
        return False
    expected = (os.getenv("QUOTEX_INGEST_SECRET") or "").strip()
    supplied = (request.headers.get("X-MMC-Quotex-Key") or request.args.get("key") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))


@app.before_request
def require_login():
    if request.endpoint in {"login", "favicon", "privacy", "static"}: return None
    if _collector_request_authenticated():
        session["authenticated"] = True
        return None
    if not session.get("authenticated"): return redirect(url_for("login"))
    return None


@app.route("/select-market", methods=["POST"])
def select_market():
    mode = request.form.get("mode", "").strip().lower()
    pair = request.form.get("pair", "").strip().upper()
    if pair not in _valid_pairs(mode): return jsonify({"ok": False, "error": "অবৈধ মার্কেট।"}), 400
    session["selected_mode"] = mode; session["selected_pair"] = pair
    return jsonify({"ok": True, "mode": mode, "pair": pair})


@app.route("/", methods=["GET", "POST"])
def index():
    result = None; error = None
    if request.method == "POST":
