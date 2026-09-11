"""Web UI for the active 1-minute Forex tick-run strategy."""
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

app = Flask(__name__)
app.secret_key = (
    os.getenv("APP_SECRET_KEY")
    or os.getenv("MASTER_SETUP_KEY")
    or os.urandom(32)
)
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
QUOTEX_OTC_LABELS = {
    "BTC/USDT": "EURUSD OTC",
    "ETH/USDT": "GBPUSD OTC",
    "BNB/USDT": "USDJPY OTC",
    "SOL/USDT": "AUDUSD OTC",
    "XRP/USDT": "USDCAD OTC",
    "ADA/USDT": "USDCHF OTC",
    "DOGE/USDT": "NZDUSD OTC",
    "AVAX/USDT": "EURJPY OTC",
    "LINK/USDT": "GBPJPY OTC",
    "LTC/USDT": "XAUUSD OTC",
}
_USAGE_CACHE = {"data": None, "at": 0.0}


def _display_pair(mode: str, pair: str) -> str:
    if mode == "crypto":
        return QUOTEX_OTC_LABELS.get(pair, pair.replace("/", "") + " OTC")
    return pair


def _usage_view():
    now = time.time()
    if now - _USAGE_CACHE["at"] >= 60 or _USAGE_CACHE["data"] is None:
        try:
            _USAGE_CACHE["data"] = fetch_api_usage()
            _USAGE_CACHE["at"] = now
        except Exception:
            pass
    minute = get_credit_usage()
    return {
        "daily_left": None,
        "daily_limit": None,
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
    return render_template("privacy.html")


@app.before_request
def require_login():
    if request.endpoint in {"login", "favicon", "privacy", "static"}:
        return None
    if not session.get("authenticated"):
        return redirect(url_for("login"))
    return None


@app.route("/select-market", methods=["POST"])
def select_market():
    mode = request.form.get("mode", "").strip().lower()
    pair = request.form.get("pair", "").strip().upper()
    valid_pairs = REAL_PAIRS if mode == "real" else CRYPTO_PAIRS if mode == "crypto" else []
    if pair not in valid_pairs:
        return jsonify({"ok": False, "error": "অবৈধ মার্কেট।"}), 400
    session["selected_mode"] = mode
    session["selected_pair"] = pair
    return jsonify({"ok": True, "mode": mode, "pair": pair, "display_pair": _display_pair(mode, pair)})


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    if request.method == "POST":
        mode = request.form.get("mode", "").strip().lower()
        pair = request.form.get("pair", "").strip().upper()
    else:
        mode = session.get("selected_mode", "")
        pair = session.get("selected_pair", "")
    if mode not in {"real", "crypto"}:
        mode, pair = "", ""
    pairs = REAL_PAIRS if mode == "real" else CRYPTO_PAIRS if mode == "crypto" else []
    if pair not in pairs:
        pair = ""
    if request.method == "POST":
        if not pair:
            error = "Please select a market before GET SIGNAL."
        else:
            session["selected_mode"] = mode
            session["selected_pair"] = pair
            try:
                result = get_signal(pair, mode)
                record_signal(result)
            except Exception as exc:
                error = str(exc)
    return render_template("index.html", real_pairs=REAL_PAIRS, crypto_pairs=CRYPTO_PAIRS,
                           mode=mode, pair=pair, error=error, result=result, usage=_usage_view())


@app.route("/auto-signal", methods=["GET"])
def auto_signal():
    mode = session.get("selected_mode", "").strip().lower()
    pair = session.get("selected_pair", "").strip().upper()
    valid_pairs = REAL_PAIRS if mode == "real" else CRYPTO_PAIRS if mode == "crypto" else []
    if pair not in valid_pairs:
        return jsonify({"ok": False, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"}), 400
    try:
        result = get_signal(pair, mode, automatic=True)
        record_signal(result)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/performance", methods=["GET", "POST"])
def performance():
    if request.method == "POST":
        return jsonify(clear_performance_history())
    return jsonify(get_performance())


@app.route("/news-alert", methods=["GET"])
def news_alert():
    mode = session.get("selected_mode", "").strip().lower()
    pair = session.get("selected_pair", "").strip().upper()
    valid_pairs = REAL_PAIRS if mode == "real" else CRYPTO_PAIRS if mode == "crypto" else []
    if pair not in valid_pairs:
        return jsonify({"ok": False, "unselected": True, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"})
    try:
        if mode == "real":
            return jsonify(get_all_news_events(mode, REAL_PAIRS, CRYPTO_PAIRS))
        return jsonify(get_weekly_news_events_for_pair(mode, REAL_PAIRS, CRYPTO_PAIRS, pair))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/news-direction", methods=["GET"])
def news_direction():
    mode = session.get("selected_mode", "").strip().lower()
    pair = session.get("selected_pair", "").strip().upper()
    valid_pairs = REAL_PAIRS if mode == "real" else CRYPTO_PAIRS if mode == "crypto" else []
    if pair not in valid_pairs:
        return jsonify({"ok": False, "unselected": True, "needed": False, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"})
    try:
        return jsonify(get_news_direction_for_pair(mode, REAL_PAIRS, CRYPTO_PAIRS, pair))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/market-status", methods=["GET"])
def market_status():
    """Return lightweight dashboard status without blocking signal generation."""
    mode = session.get("selected_mode", "").strip().lower()
    pair = session.get("selected_pair", "").strip().upper()
    valid_pairs = REAL_PAIRS if mode == "real" else CRYPTO_PAIRS if mode == "crypto" else []
    if pair not in valid_pairs:
        return jsonify({"ok": False, "unselected": True, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"})

    display_pair = _display_pair(mode, pair)
    if mode == "crypto":
        return jsonify({
            "ok": True, "pair": display_pair, "raw_pair": pair, "market_mode": "quotex_otc",
            "session": "24/7",
            "activity": "HIGH", "activity_bn": "চলমান",
            "best_window_bn": "২৪/৭ মার্কেট",
            "news_risk": "LOW", "news_risk_bn": "কম",
            "next_news_time_utc": None,
        })

    now = time.gmtime()
    weekday = now.tm_wday
    hour = now.tm_hour
    if weekday >= 5:
        session_name, activity, activity_bn, window = "Market Closed", "LOW", "কম", "পরবর্তী Forex session"
    elif hour < 7:
        session_name, activity, activity_bn, window = "Asia", "MEDIUM", "মাঝারি", "London / New York overlap"
    elif hour < 12:
        session_name, activity, activity_bn, window = "London", "HIGH", "উচ্চ", "London / New York overlap"
    elif hour < 17:
        session_name, activity, activity_bn, window = "London / New York", "HIGH", "উচ্চ", "London / New York overlap"
    else:
        session_name, activity, activity_bn, window = "New York", "MEDIUM", "মাঝারি", "London session"
    return jsonify({
        "ok": True, "pair": pair, "market_mode": mode,
        "session": session_name, "activity": activity, "activity_bn": activity_bn,
        "best_window_bn": window,
        "news_risk": "LOW", "news_risk_bn": "কম",
        "next_news_time_utc": None,
    })


@app.after_request
def add_dashboard_assets(response):
    """Load dashboard assets and inject the single performance panel."""
    if response.content_type and response.content_type.startswith("text/html"):
        html = response.get_data(as_text=True)
        css = '<link rel="stylesheet" href="/static/panel_equalizer.css">'
        script = '<script src="/static/news_persistence.js" defer></script>'
        sync_script = '''<script>
(() => {
  const mode=document.getElementById('mode'), pair=document.getElementById('pair');
  if(!mode||!pair)return;
  let last=`${mode.value}|${pair.value}`, timer=null;
  async function sync(){const value=`${mode.value}|${pair.value}`;if(!mode.value||!pair.value||value===last)return;last=value;try{const body=new URLSearchParams({mode:mode.value,pair:pair.value});const r=await fetch('/select-market',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body,credentials:'same-origin',cache:'no-store'});if(!r.ok){last='';}}catch(_){last='';}}
  function schedule(){clearTimeout(timer);timer=setTimeout(sync,120)}
  pair.addEventListener('change',schedule);document.querySelectorAll('.mode-btn').forEach(b=>b.addEventListener('click',()=>setTimeout(schedule,50)));
})();
</script>'''
        performance_markup = '''
<section id="performance-compact" class="performance-compact">
  <button type="button" id="performance-toggle" class="performance-toggle" aria-expanded="false"><span>📊 PERFORMANCE 24H</span><span id="performance-chevron">▼</span></button>'''
        marker = '<a class="download-app"'
        if marker in html:
            html = html.replace(marker, performance_markup + css + script + sync_script + marker, 1)
            response.set_data(html)
    return response
