"""Web UI for Real Forex and Quotex OTC signal generation."""
from __future__ import annotations

import hmac
import os
import time
import threading
from flask import Flask, jsonify, render_template, request, redirect, url_for, session

from signals.get_signal import get_signal
from user_performance import record_signal, get_performance, clear_performance_history
from performance import settle_pending
from data.biquote_forex import fetch_api_usage, get_credit_usage
from data.news_direction import get_news_direction_for_pair
from data.news_events import get_weekly_news_events_for_pair
from data.all_news_events import get_all_news_events
from data.otc_markets import OTC_DISPLAY_PAIRS
from auth import authenticate, create_user, ensure_env_admin, get_user, get_settings, init_user_db, save_settings

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY") or os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "1") == "1")

REAL_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "GBP/CHF",
    "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY", "EUR/AUD", "GBP/AUD",
    "AUD/CAD", "NZD/CAD",
]
QUOTEX_OTC_PAIRS = list(OTC_DISPLAY_PAIRS)
_USAGE_CACHE = {"data": None, "at": 0.0}
_SETTLE_LOCK = threading.Lock()
_SETTLE_RUNNING = False


def _usage_view():
    """Return cached API/credit usage without blocking the dashboard unnecessarily."""
    now = time.time()
    if _USAGE_CACHE["data"] is not None and now - _USAGE_CACHE["at"] < 30:
        return _USAGE_CACHE["data"]
    try:
        api_usage = fetch_api_usage() or {}
    except Exception:
        api_usage = {}
    try:
        credit_usage = get_credit_usage() or {}
    except Exception:
        credit_usage = {}
    data = {"api": api_usage, "credits": credit_usage}
    _USAGE_CACHE["data"] = data
    _USAGE_CACHE["at"] = now
    return data


def _settle_in_background():
    global _SETTLE_RUNNING
    if _SETTLE_RUNNING or not _SETTLE_LOCK.acquire(blocking=False):
        return
    _SETTLE_RUNNING = True
    def worker():
        global _SETTLE_RUNNING
        try:
            settle_pending()
        except Exception:
            pass
        finally:
            _SETTLE_RUNNING = False
            _SETTLE_LOCK.release()
    threading.Thread(target=worker, name="mmc-performance-settler", daemon=True).start()


def _record_signal_in_background(result, uid):
    if not uid:
        return
    def worker():
        try:
            record_signal(result, uid)
        except Exception:
            pass
    threading.Thread(target=worker, name="mmc-signal-recorder", daemon=True).start()


def _valid_pairs(mode: str):
    return REAL_PAIRS if mode == "real" else QUOTEX_OTC_PAIRS if mode == "quotex_otc" else []


def _user_id():
    value = session.get("user_id")
    try: return int(value) if value is not None else None
    except (TypeError, ValueError): return None


def _current_user():
    uid = _user_id()
    return get_user(uid) if uid else None


@app.route("/login", methods=["GET", "POST"])
def login():
    current_user = _current_user()
    if session.get("authenticated") and current_user: return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not password: error = "Password is required."
        else:
            try:
                ensure_env_admin(); user = authenticate(username, password)
            except Exception as exc:
                user = None; error = f"Login service unavailable: {exc}"
            if user:
                session.clear(); session["authenticated"] = True; session["user_id"] = user["id"]
                session["username"] = user["username"]
                return redirect(url_for("index"))
            if error is None: error = "Invalid username/password, or your account is awaiting owner approval."
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("authenticated") and _current_user(): return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        try:
            create_user(request.form.get("username", ""), request.form.get("password", ""), request.form.get("email", ""), active=True)
            return render_template("register.html", success="Account created. You can now log in.")
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
        mode = request.form.get("market_mode", "real").strip().lower(); pair = request.form.get("pair", "").strip().upper()
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
    expected = (os.getenv("QUOTEX_INGEST_SECRET") or "").strip(); supplied = (request.headers.get("X-MMC-Quotex-Key") or request.args.get("key") or "").strip()
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
    uid = _user_id()
    settings = get_settings(uid)
    if settings.get("market_mode") != mode or (settings.get("pair") or "").upper() != pair:
        save_settings(uid, mode, pair, settings.get("auto_signal", False), settings.get("min_confidence", 0), settings.get("timezone", "Asia/Dhaka"))
    return jsonify({"ok": True, "mode": mode, "pair": pair})


@app.route("/", methods=["GET", "POST"])
def index():
    result = None; error = None; uid = _user_id(); saved = get_settings(uid) if uid else {}; current_user = _current_user()
    if request.method == "POST": mode = request.form.get("mode", "").strip().lower(); pair = request.form.get("pair", "").strip().upper()
    else: mode = session.get("selected_mode", saved.get("market_mode", "")); pair = session.get("selected_pair", saved.get("pair", ""))
    if mode not in {"real", "quotex_otc"}: mode, pair = "", ""
    if pair not in _valid_pairs(mode): pair = ""
    if request.method == "POST":
        if not pair: error = "Please select a market before GET SIGNAL."
        else:
            session["selected_mode"] = mode; session["selected_pair"] = pair
            try:
                result = get_signal(pair, mode)
                _record_signal_in_background(result, uid)
            except Exception as exc: error = str(exc)
    return render_template("index.html", real_pairs=REAL_PAIRS, otc_pairs=QUOTEX_OTC_PAIRS, mode=mode, pair=pair, error=error, result=result, usage=_usage_view(), user=current_user, user_settings=saved)


@app.route("/auto-signal", methods=["GET"])
def auto_signal():
    uid = _user_id(); settings = get_settings(uid); mode = session.get("selected_mode", settings.get("market_mode", "")).strip().lower(); pair = session.get("selected_pair", settings.get("pair", "") or "").strip().upper()
    if pair not in _valid_pairs(mode): return jsonify({"ok": False, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"}), 400
    try:
        result = get_signal(pair, mode, automatic=True)
        _record_signal_in_background(result, uid)
        return jsonify({"ok": True, "result": result})
    except Exception as exc: return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/performance", methods=["GET", "POST"])
def performance():
    uid = _user_id()
    if request.method == "POST": return jsonify(clear_performance_history(uid))
    _settle_in_background()
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
