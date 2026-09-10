"""Dashboard-only Market State popup for the shadow market scanner.

The popup is descriptive only. It never changes the existing v2.1 signal
strategy or blocks BUY/SELL/HOLD decisions.
"""
from __future__ import annotations

from flask import jsonify, request

from data.biquote_forex import fetch_tick_history
from scanner.market_scanner import cached_scan


def init_market_scanner_ui(app):
    @app.route("/market-scanner", methods=["GET"])
    def market_scanner():
        mode = request.args.get("mode", "").strip().lower()
        pair = request.args.get("pair", "").strip().upper()
        if not pair:
            return jsonify({"ok": False, "unselected": True, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"})
        if mode not in {"real", "crypto"}:
            mode = "real"
        if mode == "crypto":
            return jsonify({"ok": False, "error": "Shadow Market Scanner এখন real Forex-এর জন্য সক্রিয়।"}), 400
        try:
            result = cached_scan(pair, fetch_tick_history)
            result["market_mode"] = mode
            return jsonify(result)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.after_request
    def inject_market_scanner_ui(response):
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            return response
        try:
            html = response.get_data(as_text=True)
        except Exception:
            return response
        if 'id="market-state-trigger"' in html:
            return response

        css = """
<style>
#market-state-trigger{display:inline-flex;align-items:center;gap:6px;margin-left:8px;padding:8px 11px;border:1px solid #b8cffd;border-radius:9px;background:#f9fbff;color:#174ea6;font-size:13px;font-weight:900;cursor:pointer;white-space:nowrap}
#market-state-trigger:hover{background:#eef5ff}
#market-state-overlay{display:none;position:fixed;inset:0;background:rgba(15,23,42,.42);z-index:5000;align-items:center;justify-content:center;padding:18px}
#market-state-overlay.open{display:flex}
.market-state-card{width:min(520px,100%);max-height:min(760px,calc(100vh - 36px));overflow:auto;background:#fff;border-radius:16px;box-shadow:0 18px 55px rgba(0,0,0,.28);border:1px solid #dbe4f0;padding:20px}
.market-state-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}
.market-state-head h3{margin:0;font-size:24px;color:#172033}
#market-state-close{border:0;background:#172033;color:#fff;border-radius:8px;padding:7px 10px;font-size:13px;font-weight:900;cursor:pointer}
.market-state-pair{font-size:14px;color:#64748b;margin-bottom:12px}
.market-state-banner{padding:14px;border-radius:12px;background:#f1f5f9;border:1px solid #dbe4f0;text-align:center;margin-bottom:12px}
.market-state-name{font-size:27px;font-weight:900;color:#174ea6}
.market-state-score{font-size:17px;font-weight:900;margin-top:3px}
.market-state-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.market-state-item{padding:11px;border:1px solid #e2e8f0;border-radius:10px;background:#fff}
.market-state-label{font-size:12px;color:#64748b}.market-state-value{font-size:16px;font-weight:900;margin-top:3px}
.market-state-note{margin-top:12px;padding:10px;border-radius:10px;background:#fff8d8;border:1px solid #f4c64e;font-size:12px;line-height:1.45;color:#5b4a00}
.market-state-loading{padding:22px;text-align:center;color:#64748b}.market-state-error{padding:12px;border-radius:10px;background:#fff1f2;border:1px solid #fecdd3;color:#b42318;font-weight:800}
@media(max-width:600px){#market-state-trigger{font-size:12px;padding:8px 9px}.market-state-card{padding:15px}.market-state-head h3{font-size:21px}.market-state-grid{grid-template-columns:1fr}.market-state-name{font-size:24px}}
</style>
"""
        trigger = '<button type="button" id="market-state-trigger" aria-haspopup="dialog" aria-controls="market-state-overlay">📊 MARKET STATE</button>'
        popup = """
<div id="market-state-overlay" role="dialog" aria-modal="true" aria-labelledby="market-state-title">
  <div class="market-state-card">
    <div class="market-state-head"><h3 id="market-state-title">📊 Market State</h3><button type="button" id="market-state-close">CLOSE</button></div>
    <div class="market-state-pair" id="market-state-pair">—</div>
    <div id="market-state-content"><div class="market-state-loading">Loading market state…</div></div>
  </div>
</div>
<script>
(function(){
  const trigger=document.getElementById('market-state-trigger');
  if(!trigger) return;
  const overlay=document.getElementById('market-state-overlay');
  const closeBtn=document.getElementById('market-state-close');
  const content=document.getElementById('market-state-content');
  const pairSelect=document.getElementById('pair');
  let timer=null;
  const esc=v=>String(v??'—').replace(/[&<>\\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\\"':'&quot;',"'":'&#39;'}[c]));
  function current(){return {mode:document.getElementById('mode')?.value||'',pair:pairSelect?.value||''}}
  function item(label,value){return `<div class="market-state-item"><div class="market-state-label">${esc(label)}</div><div class="market-state-value">${esc(value)}</div></div>`}
  function render(d){
    if(!d.ok){content.innerHTML=`<div class="market-state-error">${esc(d.error||'Market scanner unavailable.')}</div>`;return;}
    document.getElementById('market-state-pair').textContent=`${d.pair||current().pair} — ${d.market_mode==='crypto'?'CRYPTO':'REAL'}`;
    content.innerHTML=`<div class="market-state-banner"><div class="market-state-name">${esc(d.state)}</div><div class="market-state-score">Quality Score: ${esc(d.quality_score)}/100</div></div><div class="market-state-grid">${item('Trend',d.trend)}${item('Momentum',d.momentum)}${item('Volatility',d.volatility)}${item('Tick Speed',d.tick_speed)}${item('Spread State',d.spread)}${item('Spread',`${d.spread_pips} pips`)}${item('Recent Range',`${d.range_pips} pips`)}${item('Median Tick Gap',d.median_tick_gap_ms==null?'—':`${d.median_tick_gap_ms} ms`)}</div><div class="market-state-note">SHADOW MODE — এই Market State শুধু বাজারের অবস্থা দেখাচ্ছে। বর্তমান v2.1 signal logic-এর BUY/SELL/HOLD সিদ্ধান্ত এতে পরিবর্তন হচ্ছে না।</div>`;
  }
  async function load(){
    const {mode,pair}=current();
    if(!pair){render({ok:false,error:'প্রথমে একটি মার্কেট নির্বাচন করুন।'});return;}
    try{const r=await fetch(`/market-scanner?mode=${encodeURIComponent(mode)}&pair=${encodeURIComponent(pair)}`,{cache:'no-store'});render(await r.json());}
    catch(e){render({ok:false,error:'Market scanner data পাওয়া যাচ্ছে না।'});}
  }
  function open(){overlay.classList.add('open');load();clearInterval(timer);timer=setInterval(load,10000)}
  function close(){overlay.classList.remove('open');clearInterval(timer);timer=null}
  trigger.addEventListener('click',open);closeBtn.addEventListener('click',close);overlay.addEventListener('click',e=>{if(e.target===overlay)close()});document.addEventListener('keydown',e=>{if(e.key==='Escape'&&overlay.classList.contains('open'))close()});
})();
</script>
"""
        # Put only the trigger inside the existing AUTO SIGNAL/header area,
        # matching the user's marked location. The popup itself is appended
        # near the end of the document so it cannot disturb the header layout.
        header_anchor = '</span></div>\n{% if error %}'
        if header_anchor in html:
            html = html.replace(header_anchor, '</span>' + trigger + '</div>\n{% if error %}', 1)
        else:
            html = html.replace('</body>', trigger + '</body>', 1)
        html = html.replace('</head>', css + '</head>', 1)
        html = html.replace('</body>', popup + '</body>', 1)
        response.set_data(html)
        return response
