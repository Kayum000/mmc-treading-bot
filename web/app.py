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
from auth import authenticate, create_user, ensure_env_admin, get_user, get_settings, init_user_db, save_settings

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY") or os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "1") == "1")
AUTH_USERNAME = os.getenv("APP_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("APP_PASSWORD", "")

REAL_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "GBP/CHF",
    "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY", "EUR/AUD", "GBP/AUD",
    "AUD/CAD", "NZD/CAD",
]
QUOTEX_OTC_PAIRS = list(OTC_DISPLAY_PAIRS)
_USAGE_CACHE = {"data": None, "at": 0.0}


def _valid_pairs(mode: str):
    return REAL_PAIRS if mode == "real" else QUOTEX_OTC_PAIRS if mode == "quotex_otc" else []


def _user_id():
    value = session.get("user_id")
    try: return int(value) if value is not None else None
    except (TypeError, ValueError): return None


def _current_user():
    uid = _user_id()
    return get_user(uid) if uid else None


def _usage_view():
    now = time.time()
    if now - _USAGE_CACHE["at"] >= 60 or _USAGE_CACHE["data"] is None:
        try:
            _USAGE_CACHE["data"] = fetch_api_usage(); _USAGE_CACHE["at"] = now
        except Exception: pass
    minute = get_credit_usage()
    return {"daily_left": None, "daily_limit": None, "minute_left": minute.get("left"), "minute_limit": minute.get("limit")}


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated") and _current_user(): return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not password:
            error = "Password is required."
        else:
            try:
                ensure_env_admin()
                user = authenticate(username, password)
            except Exception as exc:
                user = None; error = f"Login service unavailable: {exc}"
            if user:
                session.clear(); session["authenticated"] = True; session["user_id"] = user["id"]
                session["username"] = user["username"]; session["role"] = user["role"]
                return redirect(url_for("index"))
            if error is None: error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("authenticated") and _current_user(): return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        try:
            user_id = create_user(request.form.get("username", ""), request.form.get("password", ""), request.form.get("email", ""))
            user = get_user(user_id)
            session.clear(); session["authenticated"] = True; session["user_id"] = user_id
            session["username"] = user["username"]; session["role"] = user["role"]
            return redirect(url_for("index"))
        except Exception as exc: error = str(exc)
    return render_template("register.html", error=error)


@app.route("/logout", methods=["GET"])
def logout():
    session.clear(); return redirect(url_for("login"))


@app.route("/account", methods=["GET", "POST"])
def account():
    user = _current_user()
    if not user: return redirect(url_for("login"))
    if request.method == "POST":
        mode = request.form.get("market_mode", "real").strip().lower()
        pair = request.form.get("pair", "").strip().upper()
        if pair not in _valid_pairs(mode): return jsonify({"ok": False, "error": "অবৈধ মার্কেট।"}), 400
        save_settings(user["id"], mode, pair, request.form.get("auto_signal") == "1", float(request.form.get("min_confidence", "0") or 0), request.form.get("timezone", "Asia/Dhaka"))
        return jsonify({"ok": True})
    return jsonify({"ok": True, "user": user, "settings": get_settings(user["id"])})


@app.route("/favicon.ico")
def favicon(): return redirect(url_for("static", filename="sk_bot_logo.svg"))


@app.route("/privacy")
def privacy(): return render_template("privacy.html")


def _collector_request_authenticated() -> bool:
    if request.path not in {"/quotex/ingest", "/quotex/real-ingest"}: return False
    expected = (os.getenv("QUOTEX_INGEST_SECRET") or "").strip()
    supplied = (request.headers.get("X-MMC-Quotex-Key") or request.args.get("key") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))


@app.before_request
def require_login():
    if request.endpoint in {"login", "register", "favicon", "privacy", "static"}: return None
    if _collector_request_authenticated(): return None
    if not session.get("authenticated") or not _current_user():
        if request.path in {"/news-alert", "/news-direction", "/performance", "/auto-signal", "/select-market", "/account"}:
            return jsonify({"ok": False, "authenticated": False, "error": "Session expired. Please refresh and log in again."}), 401
        return redirect(url_for("login"))
    return None


@app.route("/select-market", methods=["POST"])
def select_market():
    mode = request.form.get("mode", "").strip().lower(); pair = request.form.get("pair", "").strip().upper()
    if pair not in _valid_pairs(mode): return jsonify({"ok": False, "error": "অবৈধ মার্কেট।"}), 400
    session["selected_mode"] = mode; session["selected_pair"] = pair
    save_settings(_user_id(), mode, pair, get_settings(_user_id()).get("auto_signal", False), get_settings(_user_id()).get("min_confidence", 0), get_settings(_user_id()).get("timezone", "Asia/Dhaka"))
    return jsonify({"ok": True, "mode": mode, "pair": pair})


@app.route("/", methods=["GET", "POST"])
def index():
    result = None; error = None; uid = _user_id()
    saved = get_settings(uid) if uid else {}
    if request.method == "POST": mode = request.form.get("mode", "").strip().lower(); pair = request.form.get("pair", "").strip().upper()
    else: mode = session.get("selected_mode", saved.get("market_mode", "")); pair = session.get("selected_pair", saved.get("pair", ""))
    if mode not in {"real", "quotex_otc"}: mode, pair = "", ""
    if pair not in _valid_pairs(mode): pair = ""
    if request.method == "POST":
        if not pair: error = "Please select a market before GET SIGNAL."
        else:
            session["selected_mode"] = mode; session["selected_pair"] = pair
            try: result = get_signal(pair, mode); record_signal(result, uid)
            except Exception as exc: error = str(exc)
    return render_template("index.html", real_pairs=REAL_PAIRS, otc_pairs=QUOTEX_OTC_PAIRS, mode=mode, pair=pair, error=error, result=result, usage=_usage_view(), user=_current_user(), user_settings=saved)


@app.route("/auto-signal", methods=["GET"])
def auto_signal():
    uid = _user_id(); mode = session.get("selected_mode", get_settings(uid).get("market_mode", "")).strip().lower(); pair = session.get("selected_pair", get_settings(uid).get("pair", "") or "").strip().upper()
    if pair not in _valid_pairs(mode): return jsonify({"ok": False, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"}), 400
    try:
        result = get_signal(pair, mode, automatic=True); record_signal(result, uid); return jsonify({"ok": True, "result": result})
    except Exception as exc: return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/performance", methods=["GET", "POST"])
def performance():
    uid = _user_id()
    if request.method == "POST": return jsonify(clear_performance_history(uid))
    return jsonify(get_performance(uid))


@app.route("/news-alert", methods=["GET"])
def news_alert():
    mode = session.get("selected_mode", "").strip().lower(); pair = session.get("selected_pair", "").strip().upper()
    if pair not in _valid_pairs(mode): return jsonify({"ok": False, "unselected": True, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"})
    if mode == "quotex_otc": return jsonify({"ok": True, "market_mode": mode, "selected_pair": pair, "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "events": [], "alert_events": [], "total_events": 0, "source": "Quotex OTC — economic news filter not used"})
    try: return jsonify(get_all_news_events(mode, REAL_PAIRS))
    except Exception:
        try: return jsonify(get_weekly_news_events_for_pair(mode, REAL_PAIRS, pair))
        except Exception as exc: return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/news-direction", methods=["GET"])
def news_direction():
    mode = session.get("selected_mode", "").strip().lower(); pair = session.get("selected_pair", "").strip().upper()
    if pair not in _valid_pairs(mode): return jsonify({"ok": False, "unselected": True, "needed": False, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"})
    if mode == "quotex_otc": return jsonify({"ok": True, "needed": False, "pair": pair, "events": [], "source": "Quotex OTC"})
    try: return jsonify(get_news_direction_for_pair(mode, REAL_PAIRS, pair))
    except Exception as exc: return jsonify({"ok": False, "error": str(exc)}), 502


try:
    init_user_db(); ensure_env_admin()
except Exception:
    pass
