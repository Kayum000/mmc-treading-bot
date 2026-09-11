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
app.secret_key = os.getenv("APP_SECRET_KEY") or os.getenv("MASTER_SETUP_KEY") or os.urandom(32)
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
    "BTC/USDT": "EURUSD OTC", "ETH/USDT": "GBPUSD OTC", "BNB/USDT": "USDJPY OTC",
    "SOL/USDT": "AUDUSD OTC", "XRP/USDT": "USDCAD OTC", "ADA/USDT": "USDCHF OTC",
    "DOGE/USDT": "NZDUSD OTC", "AVAX/USDT": "EURJPY OTC", "LINK/USDT": "GBPJPY OTC",
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


@app.after_request
def add_dashboard_assets(response):
    """Remove obsolete scanner/status UI and inject the compact Performance panel."""
    if not (response.content_type or "").startswith("text/html"):
        return response
    html = response.get_data(as_text=True)

    # The legacy template still contains the old Market Status markup. Remove it
    # at the final rendering boundary so the feature is completely absent from
    # the delivered page while keeping the signal/news template stable.
    start = html.find('<aside class="panel status-panel" id="market-status-panel">')
    if start >= 0:
        end = html.find('</aside>', start)
        if end >= 0:
            html = html[:start] + html[end + len('</aside>'):]

    css = '''<link rel="stylesheet" href="/static/panel_equalizer.css"><style>
.dashboard{grid-template-columns:minmax(420px,1.25fr) minmax(320px,.9fr)!important;}
#market-status-panel{display:none!important}
@media(max-width:900px){.dashboard{grid-template-columns:1fr!important}.signal-panel{order:1}.news-box{order:2}}
.performance-compact{width:100%;margin:14px 0;background:#fff;border:1px solid #cbd5e1;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.03);overflow:hidden}.performance-toggle{width:100%;display:flex;justify-content:space-between;background:#fff;color:#172033;border:0;padding:12px 14px;font-size:16px;font-weight:900;text-align:left}.performance-body{padding:0 12px 12px;border-top:1px solid #e7ebf0}.performance-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:10px}.performance-summary>div{padding:8px 5px;text-align:center;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc}.performance-summary span{display:block;font-size:11px;color:#64748b}.performance-summary strong{display:block;font-size:17px;margin-top:2px}.performance-subhead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:10px 0 6px;font-size:12px;font-weight:800;color:#475569}.performance-actions{display:flex;gap:5px}.performance-subhead button{padding:5px 9px;font-size:13px;background:#172033;color:#fff;border:0;border-radius:7px}.performance-history{display:grid;gap:5px;max-height:260px;overflow:auto}.performance-item{display:grid;grid-template-columns:1.1fr .7fr 1fr .9fr .8fr;gap:5px;align-items:center;padding:7px 6px;border:1px solid #e2e8f0;border-radius:8px;font-size:11px}.performance-item .pair{font-weight:900}.performance-item .signal-buy,.performance-item .win{color:#16803c;font-weight:900}.performance-item .signal-sell,.performance-item .loss{color:#dc2626;font-weight:900}.performance-empty{padding:10px;border-radius:8px;background:#f8fafc;color:#64748b;font-size:12px;text-align:center}.performance-error{margin-top:7px;padding:8px;border-radius:8px;background:#fff1f2;color:#b42318;border:1px solid #fecdd3;font-size:12px}
@media(max-width:600px){.performance-summary{grid-template-columns:repeat(2,1fr)}.performance-item{grid-template-columns:1fr 1fr 1fr}.performance-item .time{grid-column:1/-1}}
</style>'''
    script = '''<script src="/static/news_persistence.js" defer></script><script>
(() => {
  const mode=document.getElementById('mode'),pair=document.getElementById('pair');
  if(mode&&pair){let last=`${mode.value}|${pair.value}`,timer=null;async function sync(){const value=`${mode.value}|${pair.value}`;if(!mode.value||!pair.value||value===last)return;last=value;try{const body=new URLSearchParams({mode:mode.value,pair:pair.value});const r=await fetch('/select-market',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body,credentials:'same-origin',cache:'no-store'});if(!r.ok)last='';}catch(_){last='';}}function schedule(){clearTimeout(timer);timer=setTimeout(sync,120)}pair.addEventListener('change',schedule);document.querySelectorAll('.mode-btn').forEach(b=>b.addEventListener('click',()=>setTimeout(schedule,50)));}
  const toggle=document.getElementById('performance-toggle'),body=document.getElementById('performance-body'),refresh=document.getElementById('performance-refresh'),clear=document.getElementById('performance-clear'),history=document.getElementById('performance-history'),err=document.getElementById('performance-error');
  if(!toggle||!body||!refresh||!clear||!history)return;
  const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render(d){if(!d.ok){err.hidden=false;err.textContent=d.error||'Performance unavailable.';return;}err.hidden=true;document.getElementById('perf-total').textContent=d.total??0;document.getElementById('perf-wins').textContent=d.wins??0;document.getElementById('perf-losses').textContent=d.losses??0;document.getElementById('perf-rate').textContent=`${d.accuracy??0}%`;const rows=d.history||[];history.innerHTML=rows.length?rows.map(x=>`<div class="performance-item"><span class="pair">${esc(x.pair)}</span><span class="${String(x.signal).toLowerCase()==='buy'?'signal-buy':'signal-sell'}">${esc(x.signal)}</span><span class="time">${esc(String(x.signal_time_utc||'').replace('T',' ').slice(0,19))}</span><span>${esc(x.result)}</span><span>${x.entry_price==null?'—':esc(x.entry_price)}</span></div>`).join(''):'<div class="performance-empty">No confirmed results in the last 24 hours.</div>';}
  async function load(){try{const r=await fetch('/performance',{cache:'no-store',credentials:'same-origin'});render(await r.json());}catch(e){err.hidden=false;err.textContent=e.message||'Performance unavailable.';}}
  toggle.addEventListener('click',()=>{const open=toggle.getAttribute('aria-expanded')==='true';toggle.setAttribute('aria-expanded',String(!open));body.hidden=open;document.getElementById('performance-chevron').textContent=open?'▼':'▲';if(!open)load();});refresh.addEventListener('click',load);clear.addEventListener('click',async()=>{if(!confirm('Clear confirmed performance history?'))return;try{const r=await fetch('/performance',{method:'POST',credentials:'same-origin'});render(await r.json());}catch(e){err.hidden=false;err.textContent=e.message||'Unable to clear performance.';}});
})();
</script>'''
    performance_markup = '''<section id="performance-compact" class="performance-compact"><button type="button" id="performance-toggle" class="performance-toggle" aria-expanded="false"><span>📊 PERFORMANCE 24H</span><span id="performance-chevron">▼</span></button><div id="performance-body" class="performance-body" hidden><div class="performance-summary"><div><span>Total</span><strong id="perf-total">—</strong></div><div><span>WIN</span><strong id="perf-wins">—</strong></div><div><span>LOSS</span><strong id="perf-losses">—</strong></div><div><span>Accuracy</span><strong id="perf-rate">—</strong></div></div><div class="performance-subhead"><span>Last 24 Hours — 1m direction</span><div class="performance-actions"><button type="button" id="performance-refresh">↻</button><button type="button" id="performance-clear">Clear</button></div></div><div id="performance-history" class="performance-history"><div class="performance-empty">Performance দেখতে খুলুন।</div></div><div id="performance-error" class="performance-error" hidden></div></div></section>'''
    marker = '<a class="download-app"'
    if marker in html and 'id="performance-compact"' not in html:
        html = html.replace('</head>', css + '</head>', 1)
        html = html.replace('<script src="{{ url_for(\'static\', filename=\'signal_alert.js\') }}"></script>', '<script src="{{ url_for(\'static\', filename=\'signal_alert.js\') }}"></script>' + script, 1)
        html = html.replace(marker, performance_markup + marker, 1)
    response.set_data(html)
    return response
