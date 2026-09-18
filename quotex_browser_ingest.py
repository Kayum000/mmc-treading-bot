"""Authenticated Quotex Real Market + OTC ingest and dynamic signal integration."""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time

from flask import jsonify, request, session

from data.quotex_otc import ingest_local_candles, local_stream_status, local_active_asset
from data.otc_markets import display_for_asset, OTC_DISPLAY_PAIRS
from signals.get_signal import get_signal

logger = logging.getLogger(__name__)

_REAL_MARKET_LOCK = threading.Lock()
_REAL_MARKET: dict[str, dict] = {}


def _collector_secret_valid() -> bool:
    expected = (os.getenv("QUOTEX_INGEST_SECRET") or "").strip()
    supplied = (request.headers.get("X-MMC-Quotex-Key") or request.args.get("key") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))


def _real_asset(value) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum() or ch in "._-")[:80]


def _store_real_market(payload: dict) -> int:
    accepted = 0
    now = time.time()
    with _REAL_MARKET_LOCK:
        for row in payload.get("candles") or []:
            if not isinstance(row, dict):
                continue
            asset = _real_asset(row.get("asset") or row.get("symbol"))
            try:
                ts = float(row.get("timestamp", row.get("time", row.get("from"))))
                o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            except (TypeError, ValueError, KeyError):
                continue
            if not asset or not all(v == v and abs(v) != float("inf") for v in (ts, o, h, l, c)):
                continue
            state = _REAL_MARKET.setdefault(asset, {"bars": [], "quote": None, "quote_history": []})
            bars = state["bars"]
            bucket = int(ts // 60) * 60
            item = {"timestamp": float(bucket), "open": o, "high": h, "low": l, "close": c}
            if bars and int(float(bars[-1]["timestamp"])) == bucket:
                bars[-1].update(item)
            else:
                bars.append(item)
            state["bars"] = bars[-300:]
            state["updated_at"] = now
            accepted += 1
        for row in payload.get("quotes") or []:
            if not isinstance(row, dict):
                continue
            asset = _real_asset(row.get("asset") or row.get("symbol"))
            try:
                price = float(row.get("price", row.get("close")))
                ts = float(row.get("timestamp", row.get("time", now)))
            except (TypeError, ValueError):
                continue
            if not asset or not price == price or abs(price) == float("inf"):
                continue
            state = _REAL_MARKET.setdefault(asset, {"bars": [], "quote": None, "quote_history": []})
            state["quote"] = {"price": price, "timestamp": ts}
            history = state.setdefault("quote_history", [])
            history.append({"price": price, "timestamp": ts})
            state["quote_history"] = history[-1000:]
            state["updated_at"] = now
            accepted += 1
    return accepted


def real_market_ticks(asset: str, count: int = 1000):
    import pandas as pd
    clean = _real_asset(asset)
    limit = max(1, min(int(count), 1000))
    with _REAL_MARKET_LOCK:
        rows = list((_REAL_MARKET.get(clean) or {}).get("quote_history", []))[-limit:]
    if not rows:
        return pd.DataFrame(columns=["timestamp", "askPrice", "bidPrice"])
    out = []
    for row in rows:
        try:
            price = float(row["price"])
            ts = pd.to_datetime(float(row["timestamp"]), unit="s", utc=True)
            spread = max(abs(price) * 0.00001, 0.00001)
            out.append({"timestamp": ts, "askPrice": price + spread / 2.0, "bidPrice": price - spread / 2.0})
        except (TypeError, ValueError, KeyError):
            continue
    return pd.DataFrame(out).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def init_quotex_browser_ingest(app):
    def allow_collector_endpoint():
        if request.endpoint in {"quotex_ingest", "quotex_real_ingest", "quotex_stream_status", "quotex_current_market"} and _collector_secret_valid():
            session["authenticated"] = True
        return None
    app.before_request_funcs.setdefault(None, []).insert(0, allow_collector_endpoint)

    @app.route("/quotex/ingest", methods=["POST"])
    def quotex_ingest():
        if not _collector_secret_valid(): return jsonify({"ok": False, "error": "Invalid ingest key."}), 401
        if not request.is_json: return jsonify({"ok": False, "error": "JSON body required."}), 415
        payload = request.get_json(silent=True) or {}
        try:
            sent_at = payload.get("sent_at")
            if sent_at is not None and abs(time.time() - float(sent_at)) > 30: return jsonify({"ok": False, "error": "Stale collector payload."}), 408
        except (TypeError, ValueError): return jsonify({"ok": False, "error": "Invalid sent_at."}), 400
        accepted = ingest_local_candles(payload)
        if not accepted: return jsonify({"ok": False, "error": "No supported closed candle data found."}), 422
        return jsonify({"ok": True, "accepted": accepted, "status": local_stream_status()})

    @app.route("/quotex/real-ingest", methods=["POST"])
    def quotex_real_ingest():
        if not _collector_secret_valid(): return jsonify({"ok": False, "error": "Invalid ingest key."}), 401
        if not request.is_json: return jsonify({"ok": False, "error": "JSON body required."}), 415
        payload = request.get_json(silent=True) or {}
        try:
            sent_at = payload.get("sent_at")
            if sent_at is not None and abs(time.time() - float(sent_at)) > 30: return jsonify({"ok": False, "error": "Stale collector payload."}), 408
        except (TypeError, ValueError): return jsonify({"ok": False, "error": "Invalid sent_at."}), 400
        return jsonify({"ok": True, "accepted": _store_real_market(payload)})

    @app.route("/quotex/real-market", methods=["GET"])
    def quotex_real_market():
        asset = _real_asset(request.args.get("asset")) or _real_asset(session.get("selected_pair", ""))
        with _REAL_MARKET_LOCK:
            state = _REAL_MARKET.get(asset, {"bars": [], "quote": None})
            return jsonify({"ok": bool(state.get("bars") or state.get("quote")), "asset": asset, "bars": list(state.get("bars") or []), "quote": state.get("quote"), "updated_at": state.get("updated_at"), "source": "Quotex browser WebSocket"})

    @app.route("/quotex/stream-status", methods=["GET"])
    def quotex_stream_status():
        result = local_stream_status()
        with _REAL_MARKET_LOCK: result["real_market_assets"] = sorted(_REAL_MARKET.keys())
        return jsonify(result)

    @app.route("/floating-signal", methods=["GET"])
    def floating_signal():
        mode = request.args.get("mode", "").strip().lower()
        pair = request.args.get("pair", "").strip().upper()
        try:
            if mode == "quotex_otc":
                if pair not in OTC_DISPLAY_PAIRS:
                    return jsonify({"ok": False, "error": "অসমর্থিত OTC মার্কেট।"}), 400
                result = get_signal(pair, "quotex_otc", automatic=True)
            elif mode == "real":
                result = get_signal(pair, "real", automatic=True)
            else:
                return jsonify({"ok": False, "error": "অসমর্থিত মার্কেট মোড।"}), 400
            return jsonify({"ok": True, "result": result})
        except Exception as exc:
            logger.exception("FLOATING_SIGNAL_FAILED mode=%s pair=%s", mode, pair)
            return jsonify({"ok": False, "error": str(exc), "error_type": type(exc).__name__}), 502

    @app.route("/quotex/floating-signal", methods=["GET"])
    def quotex_floating_signal():
        pair = request.args.get("pair", "").strip().upper()
        if pair not in OTC_DISPLAY_PAIRS:
            return jsonify({"ok": False, "error": "অসমর্থিত OTC মার্কেট।"}), 400
        try:
            result = get_signal(pair, "quotex_otc", automatic=True)
            return jsonify({"ok": True, "result": result})
        except Exception as exc:
            logger.exception("FLOATING_OTC_SIGNAL_FAILED pair=%s", pair)
            return jsonify({"ok": False, "error": str(exc), "error_type": type(exc).__name__}), 502

    @app.route("/quotex/current-market", methods=["GET"])
    def quotex_current_market():
        asset = local_active_asset()
        return jsonify({"ok": bool(asset), "market_mode": "quotex_otc", "asset": asset, "pair": display_for_asset(asset) if asset else None, "source": "Quotex local browser WebSocket collector"})

    original_select_market = app.view_functions.get("select_market")
    original_auto_signal = app.view_functions.get("auto_signal")

    def select_market_dynamic():
        mode = request.form.get("mode", "").strip().lower(); pair = request.form.get("pair", "").strip().upper()
        if mode == "quotex_otc":
            detected = local_active_asset(); detected_pair = display_for_asset(detected) if detected else None
            if detected_pair: pair = detected_pair
            if pair not in OTC_DISPLAY_PAIRS: return jsonify({"ok": False, "error": "বর্তমান OTC মার্কেট এখনো শনাক্ত হয়নি।"}), 409
            session["selected_mode"] = "quotex_otc"; session["selected_pair"] = pair
            return jsonify({"ok": True, "mode": "quotex_otc", "pair": pair, "automatic": True})
        if original_select_market is not None: return original_select_market()
        return jsonify({"ok": False, "error": "Market selector unavailable."}), 500

    def auto_signal_dynamic():
        mode = session.get("selected_mode", "").strip().lower()
        if mode == "quotex_otc":
            # At the exact minute boundary the browser collector can update
            # its active-asset marker a little later than the closed-candle
            # cache. Use the live asset when available, otherwise keep the
            # user's selected pair. Do not block the boundary on this marker.
            asset = local_active_asset()
            pair = display_for_asset(asset) if asset else (session.get("selected_pair") or "").strip().upper()
            if pair not in OTC_DISPLAY_PAIRS:
                return jsonify({"ok": False, "error": "বর্তমান Quotex OTC মার্কেট শনাক্ত হয়নি।"}), 409
            session["selected_mode"] = "quotex_otc"; session["selected_pair"] = pair

            # Try immediately at the candle boundary. If the closed candle
            # has not reached the server yet, retry briefly without changing
            # market/strategy logic. This prevents a transient collector race
            # from becoming a 502 while keeping the first attempt on time.
            last_exc = None
            for attempt in range(9):
                try:
                    result = get_signal(pair, "quotex_otc", automatic=True)
                    return jsonify({"ok": True, "result": result})
                except RuntimeError as exc:
                    last_exc = exc
                    if "local WebSocket collector" not in str(exc):
                        break
                    if attempt < 8:
                        time.sleep(0.25)
                except Exception as exc:
                    last_exc = exc
                    break

            exc = last_exc or RuntimeError("OTC signal generation failed.")
            logger.exception("AUTO_SIGNAL_OTC_FAILED pair=%s asset=%s", pair, asset)
            return jsonify({"ok": False, "error": str(exc), "error_type": type(exc).__name__}), 502
        if original_auto_signal is not None: return original_auto_signal()
        return jsonify({"ok": False, "error": "Auto signal unavailable."}), 500

    if original_select_market is not None: app.view_functions["select_market"] = select_market_dynamic
    if original_auto_signal is not None: app.view_functions["auto_signal"] = auto_signal_dynamic

    @app.after_request
    def allow_floating_extension(response):
        if request.path == "/quotex/floating-signal":
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.after_request
    def inject_otc_market_sync(response):
        if not (response.content_type or "").startswith("text/html"): return response
        html = response.get_data(as_text=True)
        if "QUOTEX_AUTO_MARKET_SYNC" in html: return response
        script = """<script id=\"QUOTEX_AUTO_MARKET_SYNC\">(()=>{const mode=document.getElementById('mode'),pair=document.getElementById('pair');const nativeFetch=window.fetch.bind(window);window.fetch=(input,init)=>{const u=typeof input==='string'?input:(input&&input.url)||'';if(u.includes('/performance'))return Promise.resolve(new Response(JSON.stringify({ok:false,error:'Performance removed'}),{status:410,headers:{'Content-Type':'application/json'}}));return nativeFetch(input,init)};let lastSyncedPair='';async function sync(){if(!mode||!pair||mode.value!=='quotex_otc')return;try{const r=await fetch('/quotex/current-market',{cache:'no-store',credentials:'same-origin'}),d=await r.json();if(!d.ok||!d.pair)return;const changed=d.pair!==lastSyncedPair;if(changed){let o=Array.from(pair.options).find(x=>x.value===d.pair);if(!o){o=document.createElement('option');o.value=d.pair;o.textContent=d.pair;o.dataset.market='quotex_otc';pair.appendChild(o)}pair.value=d.pair;lastSyncedPair=d.pair;await fetch('/select-market',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},credentials:'same-origin',body:new URLSearchParams({mode:'quotex_otc',pair:d.pair})})}}catch(_){}}sync();setInterval(sync,3000);const s=document.createElement('script');s.src='/static/quotex_real_chart.js';s.defer=true;document.body.appendChild(s);const auto=document.getElementById('auto-toggle');if(auto&&typeof runAuto==='function'&&typeof state!=='undefined'){const schedule=()=>{clearTimeout(state.autoTimer);if(!state.auto)return;const now=Date.now(),next=Math.floor(now/60000+1)*60000;state.autoTimer=setTimeout(()=>{if(!state.auto)return;runAuto();schedule()},Math.max(50,next-now+100))};auto.onchange=()=>{state.auto=auto.checked;clearTimeout(state.autoTimer);if(state.auto){const st=document.getElementById('auto-status');if(st)st.textContent='AUTO SIGNAL চালু';schedule()}else{const st=document.getElementById('auto-status');if(st)st.textContent='AUTO SIGNAL বন্ধ'}};if(auto.checked)schedule()}if(typeof state!=='undefined'){state.floatingAuto=false;state.floatingAutoTimer=null;const box=document.createElement('div');box.id='mmc-floating-auto';box.innerHTML='<button id="mmc-float-main" type="button">MMC</button><div id="mmc-float-panel"><div id="mmc-float-market">বর্তমান মার্কেট: —</div><label><input id="mmc-float-toggle" type="checkbox"> Floating Auto</label><div id="mmc-float-status">বন্ধ</div></div>';Object.assign(box.style,{position:'fixed',right:'14px',bottom:'90px',zIndex:'2147483647',fontFamily:'Arial,sans-serif'});const main=box.querySelector('#mmc-float-main'),panel=box.querySelector('#mmc-float-panel'),toggle=box.querySelector('#mmc-float-toggle'),market=box.querySelector('#mmc-float-market'),status=box.querySelector('#mmc-float-status');Object.assign(main.style,{border:'0',borderRadius:'999px',padding:'10px 14px',fontWeight:'700',cursor:'pointer',boxShadow:'0 4px 16px rgba(0,0,0,.35)'});Object.assign(panel.style,{display:'none',marginTop:'8px',padding:'10px',minWidth:'190px',borderRadius:'12px',background:'#111827',color:'#fff',boxShadow:'0 6px 22px rgba(0,0,0,.4)',fontSize:'12px'});box.querySelector('label').style.display='block';box.querySelector('label').style.marginTop='8px';status.style.marginTop='7px';document.body.appendChild(box);main.onclick=()=>{panel.style.display=panel.style.display==='none'?'block':'none'};const stopExistingAuto=()=>{state.auto=false;clearTimeout(state.autoTimer);clearInterval(state.autoTimer);if(auto){auto.checked=false;auto.dispatchEvent(new Event('change'))}else{const st=document.getElementById('auto-status');if(st)st.textContent='AUTO SIGNAL বন্ধ'}};const runFloating=async()=>{if(!state.floatingAuto)return;try{const r=await fetch('/auto-signal',{credentials:'same-origin',cache:'no-store'}),d=await r.json();if(r.ok&&d.ok){if(typeof renderResult==='function')renderResult(d.result);if(window.alertForSignal)window.alertForSignal(d.result);status.textContent='চালু • '+new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'})}else{status.textContent='Signal অপেক্ষমাণ'}}catch(_){status.textContent='সংযোগ অপেক্ষমাণ'}};const scheduleFloating=()=>{clearTimeout(state.floatingAutoTimer);if(!state.floatingAuto)return;const now=Date.now(),next=Math.floor(now/60000+1)*60000;state.floatingAutoTimer=setTimeout(async()=>{if(!state.floatingAuto)return;await runFloating();scheduleFloating()},Math.max(50,next-now+100))};toggle.onchange=()=>{state.floatingAuto=toggle.checked;clearTimeout(state.floatingAutoTimer);if(state.floatingAuto){stopExistingAuto();status.textContent='চালু • বর্তমান Auto বন্ধ করা হয়েছে';scheduleFloating()}else{status.textContent='বন্ধ'}};setInterval(()=>{market.textContent='বর্তমান মার্কেট: '+((state.pair||document.getElementById('pair')?.value||'—'))},1000)}})();document.getElementById('performance')?.remove();document.querySelectorAll('[data-scroll="performance"],#performance-toggle').forEach(e=>e.remove());</script>"""
        if "</body>" in html: response.set_data(html.replace("</body>", script + "</body>", 1))
        return response
    return app
