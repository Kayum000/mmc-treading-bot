"""Install Quotex OTC data mode into the existing Flask dashboard.

Existing REAL/CRYPTO UI and MMC logic remain unchanged. Quotex is data-only;
no order or trade method is called anywhere in this integration.
"""
from __future__ import annotations

import json
from flask import jsonify, render_template, request, session

from data.quotex_otc import OTC_PAIRS, fetch_quotex_candles, quotex_status
from signals import get_signal as signal_module
from signals.get_signal import get_signal as original_get_signal
from performance import record_signal

QUOTEX_MODE = "quotex"


def _canonical_otc_pair(value):
    """Return the canonical OTC symbol while accepting case variations."""
    raw = str(value or "").strip()
    for item in OTC_PAIRS:
        if item.lower() == raw.lower():
            return item
    return ""


def install(app):
    original_fetch_frame = signal_module._fetch_frame

    def _fetch_frame(pair, market_mode):
        if market_mode == "real" and str(pair).startswith("OTC:"):
            return fetch_quotex_candles(str(pair)[4:], "1m")
        return original_fetch_frame(pair, market_mode)

    signal_module._fetch_frame = _fetch_frame

    def get_signal_wrapper(pair, market_mode="real", automatic=False):
        mode = str(market_mode).strip().lower()
        if mode != QUOTEX_MODE:
            return original_get_signal(str(pair).strip().upper(), mode, automatic=automatic)
        pair = _canonical_otc_pair(pair)
        if not pair:
            raise ValueError("অবৈধ Quotex OTC মার্কেট।")
        result = original_get_signal(f"OTC:{pair}", "real", automatic=automatic)
        result["pair"] = pair
        result["requested_pair"] = pair
        result["market_mode"] = QUOTEX_MODE
        result["source"] = "Quotex OTC"
        return result

    import web.app as web_app
    web_app.get_signal = get_signal_wrapper

    original_index = app.view_functions["index"]
    original_select = app.view_functions["select_market"]
    original_auto = app.view_functions["auto_signal"]
    original_news = app.view_functions["news_alert"]
    original_news_direction = app.view_functions["news_direction"]
    original_status = app.view_functions["market_status"]

    def index_wrapper():
        mode = request.form.get("mode", "").strip().lower() if request.method == "POST" else session.get("selected_mode", "").strip().lower()
        raw_pair = request.form.get("pair", "") if request.method == "POST" else session.get("selected_pair", "")
        pair = _canonical_otc_pair(raw_pair) if mode == QUOTEX_MODE else str(raw_pair).strip().upper()
        if mode != QUOTEX_MODE:
            return original_index()
        result = None
        error = None
        if not pair:
            pair = _canonical_otc_pair(session.get("selected_pair", ""))
        if request.method == "POST":
            if not pair:
                error = "একটি Quotex OTC মার্কেট নির্বাচন করুন।"
            else:
                session["selected_mode"] = QUOTEX_MODE
                session["selected_pair"] = pair
                try:
                    result = get_signal_wrapper(pair, QUOTEX_MODE)
                    record_signal(result)
                except Exception as exc:
                    error = str(exc)
        return render_template("index.html", real_pairs=web_app.REAL_PAIRS, crypto_pairs=web_app.CRYPTO_PAIRS, mode=QUOTEX_MODE, pair=pair, result=result, error=error, usage=web_app._usage_view())

    def select_wrapper():
        mode = request.form.get("mode", "").strip().lower()
        raw_pair = request.form.get("pair", "")
        if mode != QUOTEX_MODE:
            return original_select()
        pair = _canonical_otc_pair(raw_pair)
        if not pair:
            return jsonify({"ok": False, "error": "অবৈধ Quotex OTC মার্কেট।"}), 400
        session["selected_mode"] = QUOTEX_MODE
        session["selected_pair"] = pair
        return jsonify({"ok": True, "mode": QUOTEX_MODE, "pair": pair})

    def auto_wrapper():
        mode = session.get("selected_mode", "").strip().lower()
        pair = _canonical_otc_pair(session.get("selected_pair", ""))
        if mode != QUOTEX_MODE:
            return original_auto()
        if not pair:
            return jsonify({"ok": False, "error": "প্রথমে একটি Quotex OTC মার্কেট নির্বাচন করুন।"}), 400
        try:
            result = get_signal_wrapper(pair, QUOTEX_MODE, automatic=True)
            record_signal(result)
            return jsonify({"ok": True, "result": result})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    def news_wrapper():
        if session.get("selected_mode", "").strip().lower() == QUOTEX_MODE:
            return jsonify({"ok": True, "events": [], "alert_events": [], "checked_at_utc": "", "note_bn": "Quotex OTC-তে সাধারণ scheduled-news filter প্রযোজ্য নয়; OTC candle data আলাদাভাবে যাচাই করা হচ্ছে।"})
        return original_news()

    def news_direction_wrapper():
        if session.get("selected_mode", "").strip().lower() == QUOTEX_MODE:
            return jsonify({"ok": True, "needed": False, "direction": "NONE"})
        return original_news_direction()

    def status_wrapper():
        mode = request.args.get("mode", session.get("selected_mode", "")).strip().lower()
        raw_pair = request.args.get("pair", session.get("selected_pair", ""))
        if mode != QUOTEX_MODE:
            return original_status()
        pair = _canonical_otc_pair(raw_pair)
        if not pair:
            return jsonify({"ok": False, "unselected": True, "error": "প্রথমে একটি Quotex OTC মার্কেট নির্বাচন করুন।"})
        session["selected_mode"] = QUOTEX_MODE
        session["selected_pair"] = pair
        return jsonify(quotex_status(pair))

    app.view_functions["index"] = index_wrapper
    app.view_functions["select_market"] = select_wrapper
    app.view_functions["auto_signal"] = auto_wrapper
    app.view_functions["news_alert"] = news_wrapper
    app.view_functions["news_direction"] = news_direction_wrapper
    app.view_functions["market_status"] = status_wrapper

    @app.after_request
    def quotex_dashboard_ui(response):
        if not response.content_type or not response.content_type.startswith("text/html"):
            return response
        html = response.get_data(as_text=True)
        marker = "</body>"
        if marker not in html:
            return response
        otc_json = json.dumps(OTC_PAIRS, ensure_ascii=False)
        script = f"""
<script>
(function(){{
const OTC_PAIRS={otc_json};
function installQuotexUI(){{
 const tabs=document.querySelector('.mode-tabs'), pair=document.getElementById('pair'), mode=document.getElementById('mode'), panel=document.getElementById('market-status-panel');
 if(!tabs||!pair||!mode||!panel)return;
 if(!tabs.querySelector('[data-mode="quotex"]')){{const b=document.createElement('button');b.type='button';b.className='mode-btn';b.dataset.mode='quotex';b.textContent='QUOTEX OTC';tabs.appendChild(b);b.addEventListener('click',()=>window.__mmcSetQuotex())}}
 OTC_PAIRS.forEach(p=>{{if(!Array.from(pair.options).some(o=>o.value===p)){{const o=document.createElement('option');o.value=p;o.textContent=p.replace('_otc',' OTC');o.dataset.market='quotex';pair.appendChild(o)}}}});
 window.__mmcSetQuotex=function(){{
  mode.value='quotex';document.querySelectorAll('.mode-btn').forEach(b=>b.classList.toggle('active',b.dataset.mode==='quotex'));Array.from(pair.options).forEach(o=>o.hidden=o.dataset.market!=='quotex');const saved=localStorage.getItem('mmc_selected_quotex_pair')||OTC_PAIRS[0];pair.value=saved;if(pair.value!==saved)pair.value='';if(pair.value)localStorage.setItem('mmc_selected_quotex_pair',pair.value);document.getElementById('signal-button').disabled=!pair.value;
  panel.innerHTML='<h2 class="status-title">📡 Quotex OTC</h2><div class="status-pair" id="qx-pair">'+(pair.value||'মার্কেট নির্বাচন করুন')+'</div><div class="status-row"><div class="status-label">ডাটা সোর্স</div><div class="status-value">Quotex OTC</div></div><div class="status-row"><div class="status-label">কানেকশন</div><div class="status-value" id="qx-connection">যাচাই হচ্ছে…</div></div><div class="status-row"><div class="status-label">টাইমফ্রেম</div><div class="status-value">1 মিনিট</div></div><div class="status-row"><div class="status-label">বন্ধ ক্যান্ডেল</div><div class="status-value" id="qx-count">—</div></div><div class="status-row"><div class="status-label">সর্বশেষ বন্ধ ক্যান্ডেল</div><div class="status-value" id="qx-latest">—</div></div><div class="status-recommendation" id="qx-note">GET SIGNAL চাপলে নির্বাচিত OTC-এর বন্ধ 1m data দিয়ে MMC analysis হবে।</div><div class="status-note">Quotex OTC থেকে শুধু market data নেওয়া হচ্ছে; কোনো trade/order পাঠানো হয় না।</div>';window.__mmcCheckQuotexStatus();
 }};
 window.__mmcCheckQuotexStatus=async function(){{if(mode.value!=='quotex'||!pair.value)return;try{{const r=await fetch('/market-status?mode=quotex&pair='+encodeURIComponent(pair.value),{{cache:'no-store'}});const d=await r.json();const c=document.getElementById('qx-connection');if(!c)return;c.textContent=d.ok?'সংযুক্ত / ডাটা পাওয়া যাচ্ছে':'সংযোগ বা ডাটা সমস্যা';c.className='status-value '+(d.ok?'status-low':'status-high');if(d.ok){{document.getElementById('qx-count').textContent=d.closed_candles+'টি';document.getElementById('qx-latest').textContent=d.latest_closed_candle||'—';document.getElementById('qx-note').textContent='Quotex OTC candle data ঠিকভাবে পাওয়া গেছে। এখন GET SIGNAL দিয়ে MMC যাচাই করুন।'}}else document.getElementById('qx-note').textContent=d.error||'Quotex OTC data পাওয়া যায়নি।'}}catch(e){{const c=document.getElementById('qx-connection');if(c)c.textContent='ডাটা যাচাই ব্যর্থ';}}}};
 const originalScheduleStatus=window.scheduleStatus;window.scheduleStatus=function(){{if(mode.value==='quotex'){{window.__mmcCheckQuotexStatus();return}}originalScheduleStatus()}};
 const originalScheduleNews=window.scheduleNews;window.scheduleNews=function(){{if(mode.value==='quotex'){{document.getElementById('news-content').innerHTML='<div class="news-empty">Quotex OTC-এর জন্য সাধারণ scheduled news filter ব্যবহার করা হচ্ছে না।</div>';document.getElementById('news-state').textContent='OTC candle data আলাদাভাবে যাচাই হচ্ছে।';return}}originalScheduleNews()}};
 pair.addEventListener('change',()=>{{if(mode.value==='quotex'){{localStorage.setItem('mmc_selected_quotex_pair',pair.value);window.__mmcCheckQuotexStatus()}}}});
 document.getElementById('signal-form').addEventListener('submit',()=>{{if(mode.value==='quotex'&&pair.value){{mode.value='quotex';localStorage.setItem('mmc_selected_quotex_pair',pair.value)}}}});
 if(mode.value==='quotex')window.__mmcSetQuotex();
}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',installQuotexUI);else installQuotexUI();
}})();
</script>
"""
        response.set_data(html.replace(marker, script + marker))
        return response
