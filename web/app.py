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
QUOTEX_OTC_PAIRS = [
    "EURUSD OTC", "GBPUSD OTC", "USDJPY OTC", "AUDUSD OTC", "USDCAD OTC",
    "USDCHF OTC", "NZDUSD OTC", "EURJPY OTC", "GBPJPY OTC", "XAUUSD OTC", "USDARS OTC",
]
_USAGE_CACHE = {"data": None, "at": 0.0}

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
    if session.get("authenticated"): return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username=request.form.get("username",""); password=request.form.get("password","")
        if not AUTH_PASSWORD: error="Login is not configured yet. Set APP_PASSWORD in the server environment."
        elif hmac.compare_digest(username,AUTH_USERNAME) and hmac.compare_digest(password,AUTH_PASSWORD):
            session.clear(); session["authenticated"]=True; return redirect(url_for("index"))
        else: error="Invalid username or password."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))
@app.route("/favicon.ico")
def favicon(): return redirect(url_for("static", filename="sk_bot_logo.svg"))
@app.route("/privacy")
def privacy(): return render_template("privacy.html")

@app.before_request
def require_login():
    if request.endpoint in {"login","favicon","privacy","static"}: return None
    if not session.get("authenticated"): return redirect(url_for("login"))
    return None

def _valid_pairs(mode):
    return REAL_PAIRS if mode == "real" else QUOTEX_OTC_PAIRS if mode == "quotex_otc" else []

@app.route("/select-market", methods=["POST"])
def select_market():
    mode=request.form.get("mode","").strip().lower(); pair=request.form.get("pair","").strip().upper()
    if pair not in _valid_pairs(mode): return jsonify({"ok":False,"error":"অবৈধ মার্কেট।"}),400
    session["selected_mode"]=mode; session["selected_pair"]=pair
    return jsonify({"ok":True,"mode":mode,"pair":pair})

@app.route("/", methods=["GET","POST"])
def index():
    result=None; error=None
    if request.method=="POST": mode=request.form.get("mode","").strip().lower(); pair=request.form.get("pair","").strip().upper()
    else: mode=session.get("selected_mode",""); pair=session.get("selected_pair","")
    if mode not in {"real","quotex_otc"}: mode=""; pair=""
    if pair not in _valid_pairs(mode): pair=""
    if request.method=="POST":
        if not pair: error="Please select a market before GET SIGNAL."
        else:
            session["selected_mode"]=mode; session["selected_pair"]=pair
            try: result=get_signal(pair,mode); record_signal(result)
            except Exception as exc: error=str(exc)
    return render_template("index.html",real_pairs=REAL_PAIRS,otc_pairs=QUOTEX_OTC_PAIRS,mode=mode,pair=pair,error=error,result=result,usage=_usage_view())

@app.route("/auto-signal")
def auto_signal():
    mode=session.get("selected_mode","").strip().lower(); pair=session.get("selected_pair","").strip().upper()
    if pair not in _valid_pairs(mode): return jsonify({"ok":False,"error":"প্রথমে একটি মার্কেট নির্বাচন করুন।"}),400
    try:
        result=get_signal(pair,mode,automatic=True); record_signal(result); return jsonify({"ok":True,"result":result})
    except Exception as exc: return jsonify({"ok":False,"error":str(exc)}),502

@app.route("/performance", methods=["GET","POST"])
def performance(): return jsonify(clear_performance_history()) if request.method=="POST" else jsonify(get_performance())

@app.route("/news-alert")
def news_alert():
    mode=session.get("selected_mode","").strip().lower(); pair=session.get("selected_pair","").strip().upper()
    if pair not in _valid_pairs(mode): return jsonify({"ok":False,"unselected":True,"error":"প্রথমে একটি মার্কেট নির্বাচন করুন।"})
    if mode=="quotex_otc":
        return jsonify({"ok":True,"market_mode":mode,"selected_pair":pair,"checked_at_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"events":[],"alert_events":[],"total_events":0,"source":"Quotex OTC — economic news filter not used"})
    try: return jsonify(get_all_news_events(mode,REAL_PAIRS,[]))
    except Exception:
        try: return jsonify(get_weekly_news_events_for_pair(mode,REAL_PAIRS,[],pair))
        except Exception as exc: return jsonify({"ok":False,"error":str(exc)}),502

@app.route("/news-direction")
def news_direction():
    mode=session.get("selected_mode","").strip().lower(); pair=session.get("selected_pair","").strip().upper()
    if pair not in _valid_pairs(mode): return jsonify({"ok":False,"unselected":True,"needed":False,"error":"প্রথমে একটি মার্কেট নির্বাচন করুন।"})
    if mode=="quotex_otc": return jsonify({"ok":True,"needed":False,"pair":pair,"events":[],"source":"Quotex OTC"})
    try: return jsonify(get_news_direction_for_pair(mode,REAL_PAIRS,[],pair))
    except Exception as exc: return jsonify({"ok":False,"error":str(exc)}),502

@app.route("/market-status")
def market_status():
    mode=session.get("selected_mode","").strip().lower(); pair=session.get("selected_pair","").strip().upper()
    if pair not in _valid_pairs(mode): return jsonify({"ok":False})
    otc=mode=="quotex_otc"
    return jsonify({"ok":True,"pair":pair,"session":"24/7 OTC" if otc else "Forex Session","activity":"HIGH" if otc else "MEDIUM","activity_bn":"HIGH" if otc else "MEDIUM","best_window_bn":"24/7 OTC Market" if otc else "London / New York overlap","news_risk":"LOW","news_risk_bn":"LOW","next_news_time_utc":None})

@app.after_request
def add_dashboard_assets(response):
    if not (response.content_type or "").startswith("text/html"): return response
    html=response.get_data(as_text=True)
    css='''<style>.performance-compact{width:100%;margin:14px 0;background:#fff;border:1px solid #cbd5e1;border-radius:10px;overflow:hidden}.performance-toggle{width:100%;display:flex;justify-content:space-between;background:#fff;color:#172033;border:0;padding:12px 14px;font-size:16px;font-weight:900}.performance-body{padding:0 12px 12px;border-top:1px solid #e7ebf0}.performance-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:10px}.performance-summary>div{padding:8px;text-align:center;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc}.performance-summary span{display:block;font-size:11px;color:#64748b}.performance-summary strong{display:block;font-size:17px}.performance-history{display:grid;gap:5px;max-height:260px;overflow:auto}.performance-item{display:grid;grid-template-columns:1.1fr .7fr 1fr .9fr .8fr;gap:5px;align-items:center;padding:7px 6px;border:1px solid #e2e8f0;border-radius:8px;font-size:11px}.performance-item .pair{font-weight:900}.performance-empty{padding:10px;background:#f8fafc;color:#64748b;font-size:12px;text-align:center}.performance-error{margin-top:7px;padding:8px;background:#fff1f2;color:#b42318;border:1px solid #fecdd3;font-size:12px}</style>'''
    script='''<script>document.addEventListener('DOMContentLoaded',()=>{const t=document.getElementById('performance-toggle'),b=document.getElementById('performance-body'),h=document.getElementById('performance-history'),e=document.getElementById('performance-error');if(!t)return;const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));async function load(){try{const r=await fetch('/performance',{cache:'no-store'}),d=await r.json();if(!d.ok)throw Error(d.error||'Performance unavailable');document.getElementById('perf-total').textContent=d.total??0;document.getElementById('perf-wins').textContent=d.wins??0;document.getElementById('perf-losses').textContent=d.losses??0;document.getElementById('perf-rate').textContent=(d.accuracy??0)+'%';h.innerHTML=(d.history||[]).length?(d.history||[]).map(x=>`<div class="performance-item"><span class="pair">${esc(x.pair)}</span><span>${esc(x.signal)}</span><span>${esc(String(x.signal_time_utc||'').replace('T',' ').slice(0,19))}</span><span>${esc(x.result)}</span><span>${x.entry_price==null?'—':esc(x.entry_price)}</span></div>`).join(''):'<div class="performance-empty">No confirmed results in the last 24 hours.</div>';e.hidden=true}catch(x){e.hidden=false;e.textContent=x.message}}t.onclick=()=>{const open=t.getAttribute('aria-expanded')==='true';t.setAttribute('aria-expanded',String(!open));b.hidden=open;if(!open)load()};document.getElementById('performance-refresh').onclick=load;document.getElementById('performance-clear').onclick=async()=>{if(confirm('Clear confirmed performance history?')){await fetch('/performance',{method:'POST'});load()}}});</script>'''
    markup='''<section id="performance-compact" class="performance-compact"><button type="button" id="performance-toggle" class="performance-toggle" aria-expanded="false"><span>📊 PERFORMANCE 24H</span><span>▼</span></button><div id="performance-body" class="performance-body" hidden><div class="performance-summary"><div><span>Total</span><strong id="perf-total">—</strong></div><div><span>WIN</span><strong id="perf-wins">—</strong></div><div><span>LOSS</span><strong id="perf-losses">—</strong></div><div><span>Accuracy</span><strong id="perf-rate">—</strong></div></div><div style="display:flex;justify-content:space-between;margin:10px 0 6px;font-size:12px;font-weight:800"><span>Last 24 Hours — 1m direction</span><span><button type="button" id="performance-refresh">↻</button> <button type="button" id="performance-clear">Clear</button></span></div><div id="performance-history" class="performance-history"><div class="performance-empty">Performance দেখতে খুলুন।</div></div><div id="performance-error" class="performance-error" hidden></div></div></section>'''
    if '<a class="download"' in html and 'id="performance-compact"' not in html:
        html=html.replace('</head>',css+'</head>',1).replace('<a class="download"',markup+'<a class="download"',1).replace('</body>',script+'</body>',1)
    response.set_data(html); return response
