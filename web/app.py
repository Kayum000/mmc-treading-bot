"""Web UI for Real Forex and Crypto MMC signals."""
from __future__ import annotations

import hmac
import os
import time
from flask import Flask, jsonify, render_template, request, redirect, url_for, session

from signals.get_signal import get_signal
from performance import record_signal, get_performance
from data.twelve_data_forex import fetch_api_usage, get_credit_usage
from data.news_direction import get_news_direction_for_pair
from data.news_events import get_weekly_news_events_for_pair
from data.all_news_events import get_all_news_events
from data.market_status import get_market_status

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
    """Store UI market selection without generating a signal or consuming market-data credits."""
    mode = request.form.get("mode", "").strip().lower()
    pair = request.form.get("pair", "").strip().upper()
    valid_pairs = REAL_PAIRS if mode == "real" else CRYPTO_PAIRS if mode == "crypto" else []
    if pair not in valid_pairs:
        return jsonify({"ok": False, "error": "অবৈধ মার্কেট।"}), 400
    session["selected_mode"] = mode
    session["selected_pair"] = pair
    return jsonify({"ok": True, "mode": mode, "pair": pair})


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
        mode = ""
        pair = ""

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


@app.route("/auto-signal", methods=["GET"])
def auto_signal():
    """Generate an automatic signal only for the user's selected market."""
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


@app.route("/performance", methods=["GET"])
def performance():
    """Return the last 24h confirmed BUY/SELL performance and settle due entries."""
    return jsonify(get_performance())


@app.route("/news-alert", methods=["GET"])
def news_alert():
    """Return all Real/Forex news together; keep Crypto news behavior unchanged."""
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
    """Use the event-keyed direction cache; Alpha Vantage is called only once per news event."""
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
    """Return session/activity/news-risk status for the selected market only."""
    mode = session.get("selected_mode", "").strip().lower()
    pair = session.get("selected_pair", "").strip().upper()
    valid_pairs = REAL_PAIRS if mode == "real" else CRYPTO_PAIRS if mode == "crypto" else []
    if pair not in valid_pairs:
        return jsonify({"ok": False, "unselected": True, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"})
    try:
        return jsonify(get_market_status(mode, pair, REAL_PAIRS, CRYPTO_PAIRS))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.after_request
def add_dashboard_assets(response):
    """Load dashboard-only assets and synchronize UI market selection with the Flask session."""
    if response.content_type and response.content_type.startswith("text/html"):
        html = response.get_data(as_text=True)
        css = '<link rel="stylesheet" href="/static/panel_equalizer.css">'
        script = '<script src="/static/news_persistence.js" defer></script>'
        sync_script = '''<script>
(() => {
  const mode = document.getElementById('mode');
  const pair = document.getElementById('pair');
  if (!mode || !pair) return;
  let last = `${mode.value}|${pair.value}`;
  let timer = null;
  async function syncSelection() {
    const value = `${mode.value}|${pair.value}`;
    if (!mode.value || !pair.value || value === last) return;
    last = value;
    try {
      const body = new URLSearchParams({mode: mode.value, pair: pair.value});
      await fetch('/select-market', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded', 'Accept':'application/json'}, body, credentials:'same-origin', cache:'no-store'});
      window.location.reload();
    } catch (_) {}
  }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(syncSelection, 120);
  }
  pair.addEventListener('change', schedule);
  document.querySelectorAll('.mode-btn').forEach((button) => button.addEventListener('click', () => setTimeout(schedule, 50)));
})();
</script>'''
        performance_markup = '''
<section id="performance-compact" class="performance-compact">
  <button type="button" id="performance-toggle" class="performance-toggle" aria-expanded="false">
    <span>📊 PERFORMANCE 24H</span><span id="performance-chevron">▼</span>
  </button>
  <div id="performance-body" class="performance-body" hidden>
    <div class="performance-summary">
      <div><span>Total</span><strong id="perf-total">—</strong></div>
      <div><span>WIN</span><strong id="perf-wins">—</strong></div>
      <div><span>LOSS</span><strong id="perf-losses">—</strong></div>
      <div><span>Win Rate</span><strong id="perf-rate">—</strong></div>
    </div>
    <div class="performance-subhead"><span>Last 24 Hours — BUY/SELL only</span><button type="button" id="performance-refresh">↻</button></div>
    <div id="performance-history" class="performance-history"><div class="performance-empty">Performance দেখতে খুলুন।</div></div>
    <div id="performance-error" class="performance-error" hidden></div>
  </div>
</section>
<style>
.performance-compact{width:100%;margin:0 0 14px;background:#fff;border:1px solid #cbd5e1;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.03);overflow:hidden}
.performance-toggle{width:100%;display:flex;justify-content:space-between;align-items:center;background:#fff;color:#172033;border:0;border-radius:0;padding:12px 14px;font-size:16px;font-weight:900;text-align:left}
.performance-toggle:hover{background:#f8fafc}
.performance-body{padding:0 12px 12px;border-top:1px solid #e7ebf0}
.performance-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:10px}
.performance-summary>div{padding:8px 5px;text-align:center;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc}
.performance-summary span{display:block;font-size:11px;color:#64748b}.performance-summary strong{display:block;font-size:17px;margin-top:2px}
.performance-subhead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:10px 0 6px;font-size:12px;font-weight:800;color:#475569}
.performance-subhead button{padding:5px 9px;font-size:13px;background:#172033;color:#fff;border:0;border-radius:7px}
.performance-history{display:grid;gap:5px;max-height:260px;overflow:auto}
.performance-item{display:grid;grid-template-columns:1.1fr .7fr 1fr .9fr .8fr;gap:5px;align-items:center;padding:7px 6px;border:1px solid #e2e8f0;border-radius:8px;font-size:11px;background:#fff}
.performance-item .pair{font-weight:900}.performance-item .signal-buy{color:#16803c;font-weight:900}.performance-item .signal-sell{color:#dc2626;font-weight:900}.performance-item .win{color:#16803c;font-weight:900}.performance-item .loss{color:#dc2626;font-weight:900}
.performance-empty{padding:10px;border-radius:8px;background:#f8fafc;color:#64748b;font-size:12px;text-align:center}
.performance-error{margin-top:7px;padding:8px;border-radius:8px;background:#fff1f2;color:#b42318;border:1px solid #fecdd3;font-size:11px}
@media(max-width:600px){.performance-summary strong{font-size:16px}.performance-item{grid-template-columns:1fr .55fr 1fr .75fr .65fr;font-size:10px;padding:6px 4px}.performance-toggle{font-size:15px}}
</style>
<script>
(() => {
  const box=document.getElementById('performance-compact');
  const toggle=document.getElementById('performance-toggle');
  const body=document.getElementById('performance-body');
  const history=document.getElementById('performance-history');
  const error=document.getElementById('performance-error');
  const refresh=document.getElementById('performance-refresh');
  if(!box||!toggle||!body||!history)return;
  const esc=v=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
  const price=v=>v==null?'—':Number(v).toFixed(5).replace(/0+$/,'').replace(/\.$/,'');
  const time=v=>{const d=new Date(v);if(Number.isNaN(d.getTime()))return '—';return new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Dhaka',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d)};
  async function loadPerformance(){
    error.hidden=true;
    history.innerHTML='<div class="performance-empty">ফলাফল যাচাই হচ্ছে…</div>';
    try{
      const r=await fetch('/performance',{method:'GET',cache:'no-store',headers:{'Accept':'application/json'},credentials:'same-origin'});
      const d=await r.json();
      if(!r.ok||!d.ok)throw new Error(d.error||'Performance data পাওয়া যায়নি।');
      document.getElementById('perf-total').textContent=d.total??0;
      document.getElementById('perf-wins').textContent=d.wins??0;
      document.getElementById('perf-losses').textContent=d.losses??0;
      document.getElementById('perf-rate').textContent=`${Number(d.win_rate||0).toFixed(2)}%`;
      const rows=d.history||[];
      if(!rows.length){history.innerHTML='<div class="performance-empty">শেষ ২৪ ঘণ্টায় কোনো confirmed BUY/SELL result নেই।</div>';return}
      history.innerHTML=rows.map(x=>`<div class="performance-item"><span class="pair">${esc(x.pair)}<br><small>${esc(String(x.market_mode||'').toUpperCase())}</small></span><span class="${x.signal==='BUY'?'signal-buy':'signal-sell'}">${esc(x.signal)}</span><span>${esc(time(x.entry_time_utc))}</span><span>${esc(price(x.entry_price))}<br>${esc(price(x.result_price))}</span><span class="${x.result==='WIN'?'win':'loss'}">${esc(x.result)}</span></div>`).join('');
    }catch(e){history.innerHTML='<div class="performance-empty">Performance data এখন পাওয়া যাচ্ছে না।</div>';error.textContent=e.message||'Performance error';error.hidden=false;}
  }
  toggle.addEventListener('click',()=>{const open=toggle.getAttribute('aria-expanded')==='true';toggle.setAttribute('aria-expanded',String(!open));body.hidden=open;document.getElementById('performance-chevron').textContent=open?'▼':'▲';if(!open)loadPerformance()});
  refresh.addEventListener('click',loadPerformance);
})();
</script>
'''
        if "</head>" in html and css not in html:
            html = html.replace("</head>", css + "</head>", 1)
        if "<div class=\"dashboard\">" in html and "id=\"performance-compact\"" not in html:
            html = html.replace('<div class="dashboard">', performance_markup + '<div class="dashboard">', 1)
        if "</body>" in html and script not in html:
            html = html.replace("</body>", sync_script + script + "</body>", 1)
        response.set_data(html)
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
