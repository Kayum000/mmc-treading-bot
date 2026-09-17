"""Web UI for Real Forex and Quotex OTC signal generation."""
from __future__ import annotations

import hmac
import os
import time
import threading
from flask import Flask, jsonify, render_template, request, redirect, url_for, session

from signals.get_signal import get_signal
from performance import record_signal, get_performance, clear_performance_history, settle_pending
from data.biquote_forex import fetch_api_usage, get_credit_usage
from data.news_direction import get_news_direction_for_pair
from data.news_events import get_weekly_news_events_for_pair
from data.all_news_events import get_all_news_events
from data.otc_markets import OTC_DISPLAY_PAIRS

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

_SINGLE_USER = {
    "id": 1,
    "username": "owner",
    "email": "",
    "role": "owner",
    "full_name": "MMC Owner",
    "active": True,
}
_DEFAULT_SETTINGS = {
    "market_mode": "",
    "pair": None,
    "auto_signal": False,
    "min_confidence": 0.0,
    "timezone": "Asia/Dhaka",
}
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


def _record_signal_in_background(result):
    def worker():
        try:
            record_signal(result)
        except Exception:
            pass
    threading.Thread(target=worker, name="mmc-signal-recorder", daemon=True).start()


def _valid_pairs(mode: str):
    return REAL_PAIRS if mode == "real" else QUOTEX_OTC_PAIRS if mode == "quotex_otc" else []


def _settings():
    value = dict(_DEFAULT_SETTINGS)
    value.update(session.get("settings") or {})
    mode = session.get("selected_mode")
    pair = session.get("selected_pair")
    if mode:
        value["market_mode"] = mode
    if pair:
        value["pair"] = pair
    return value


def _save_settings(mode: str, pair: str, auto_signal=None, min_confidence=None, timezone=None):
    current = _settings()
    current["market_mode"] = mode
    current["pair"] = pair
    if auto_signal is not None:
        current["auto_signal"] = bool(auto_signal)
    if min_confidence is not None:
        current["min_confidence"] = float(min_confidence)
    if timezone:
        current["timezone"] = timezone
    session["settings"] = current
    session["selected_mode"] = mode
    session["selected_pair"] = pair
    return current


@app.route("/account", methods=["GET", "POST"])
def account():
    if request.method == "POST":
        mode = request.form.get("market_mode", "real").strip().lower()
        pair = request.form.get("pair", "").strip().upper()
        if pair not in _valid_pairs(mode):
            return jsonify({"ok": False, "error": "অবৈধ মার্কেট।"}), 400
        settings = _save_settings(
            mode,
            pair,
            request.form.get("auto_signal") == "1",
            float(request.form.get("min_confidence", "0") or 0),
            request.form.get("timezone", "Asia/Dhaka"),
        )
        return jsonify({"ok": True, "user": _SINGLE_USER, "settings": settings})
    return jsonify({"ok": True, "user": _SINGLE_USER, "settings": _settings()})


@app.route("/logout", methods=["GET", "POST"])
def logout():
    """Keep the legacy dashboard link safe after removing multi-user authentication."""
    session.clear()
    return redirect(url_for("index"))


@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="sk_bot_logo.svg"))


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


def _collector_request_authenticated() -> bool:
    if request.path not in {"/quotex/ingest", "/quotex/real-ingest"}:
        return False
    expected = (os.getenv("QUOTEX_INGEST_SECRET") or "").strip()
    supplied = (request.headers.get("X-MMC-Quotex-Key") or request.args.get("key") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))


@app.before_request
def require_dashboard():
    # The dashboard is intentionally single-user; collector endpoints still require their secret.
    if _collector_request_authenticated():
        return None
    return None


@app.route("/select-market", methods=["POST"])
def select_market():
    mode = request.form.get("mode", "").strip().lower()
    pair = request.form.get("pair", "").strip().upper()
    if pair not in _valid_pairs(mode):
        return jsonify({"ok": False, "error": "অবৈধ মার্কেট।"}), 400
    _save_settings(mode, pair)
    return jsonify({"ok": True, "mode": mode, "pair": pair})


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    saved = _settings()
    if request.method == "POST":
        mode = request.form.get("mode", "").strip().lower()
        pair = request.form.get("pair", "").strip().upper()
    else:
        mode = session.get("selected_mode", saved.get("market_mode", ""))
        pair = session.get("selected_pair", saved.get("pair", ""))
    if mode not in {"real", "quotex_otc"}:
        mode, pair = "", ""
    if pair not in _valid_pairs(mode):
        pair = ""
    if request.method == "POST":
        if not pair:
            error = "Please select a market before GET SIGNAL."
        else:
            _save_settings(mode, pair)
            try:
                result = get_signal(pair, mode)
                _record_signal_in_background(result)
            except Exception as exc:
                error = str(exc)
    return render_template(
        "index.html",
        real_pairs=REAL_PAIRS,
        otc_pairs=QUOTEX_OTC_PAIRS,
        mode=mode,
        pair=pair,
        error=error,
        result=result,
        usage=_usage_view(),
        user=_SINGLE_USER,
        user_settings=saved,
    )


@app.route("/auto-signal", methods=["GET"])
def auto_signal():
    settings = _settings()
    mode = session.get("selected_mode", settings.get("market_mode", "")).strip().lower()
    pair = session.get("selected_pair", settings.get("pair", "") or "").strip().upper()
    if pair not in _valid_pairs(mode):
        return jsonify({"ok": False, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"}), 400
    try:
        result = get_signal(pair, mode, automatic=True)
        _record_signal_in_background(result)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/performance", methods=["GET", "POST"])
def performance():
    if request.method == "POST":
        return jsonify(clear_performance_history())
    _settle_in_background()
    return jsonify(get_performance())


@app.route("/news-alert", methods=["GET"])
def news_alert():
    mode = session.get("selected_mode", "").strip().lower()
    pair = session.get("selected_pair", "").strip().upper()
    if pair not in _valid_pairs(mode):
        return jsonify({"ok": False, "unselected": True, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"})
    if mode == "quotex_otc":
        return jsonify({"ok": True, "market_mode": mode, "selected_pair": pair, "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "events": [], "alert_events": [], "total_events": 0, "source": "Quotex OTC — economic news filter not used"})
    try:
        return jsonify(get_all_news_events(mode, REAL_PAIRS))
    except Exception:
        try:
            return jsonify(get_weekly_news_events_for_pair(mode, REAL_PAIRS, pair))
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/news-direction", methods=["GET"])
def news_direction():
    mode = session.get("selected_mode", "").strip().lower()
    pair = session.get("selected_pair", "").strip().upper()
    if pair not in _valid_pairs(mode):
        return jsonify({"ok": False, "unselected": True, "needed": False, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"})
    if mode == "quotex_otc":
        return jsonify({"ok": True, "needed": False, "pair": pair, "events": [], "source": "Quotex OTC"})
    try:
        return jsonify(get_news_direction_for_pair(mode, pair))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")), debug=False)
