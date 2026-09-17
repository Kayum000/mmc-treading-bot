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
            deadline = time.monotonic() + 2.5
            asset = local_active_asset()
            while not asset and time.monotonic() < deadline:
                time.sleep(0.25)
                asset = local_active_asset()
            pair = display_for_asset(asset) if asset else None
            if not pair: return jsonify({"ok": False, "error": "বর্তমান Quotex OTC মার্কেট শনাক্ত হয়নি।"}), 409
            session["selected_mode"] = "quotex_otc"; session["selected_pair"] = pair
            try:
                result = get_signal(pair, "quotex_otc", automatic=True)
                return jsonify({"ok": True, "result": result})
            except Exception as exc:
                logger.exception("AUTO_SIGNAL_OTC_FAILED pair=%s asset=%s", pair, asset)
                return jsonify({"ok": False, "error": str(exc), "error_type": type(exc).__name__}), 502
        if original_auto_signal is not None: return original_auto_signal()
        return jsonify({"ok": False, "error": "Auto signal unavailable."}), 500

    if original_select_market is not None: app.view_functions["select_market"] = select_market_dynamic
    if original_auto_signal is not None: app.view_functions["auto_signal"] = auto_signal_dynamic

    @app.after_request
    def inject_otc_market_sync(response):
        if not (response.content_type or "").startswith("text/html"): return response
        html = response.get_data(as_text=True)
        if "QUOTEX_AUTO_MARKET_SYNC" in html: return response
        script = """<script id=\"QUOTEX_AUTO_MARKET_SYNC\">(()=>{const mode=document.getElementById('mode'),pair=document.getElementById('pair');const nativeFetch=window.fetch.bind(window);window.fetch=(input,init)=>{const u=typeof input==='string'?input:(input&&input.url)||'';if(u.includes('/performance'))return Promise.resolve(new Response(JSON.stringify({ok:false,error:'Performance removed'}),{status:410,headers:{'Content-Type':'application/json'}}));return nativeFetch(input,init)};let lastSyncedPair='';async function sync(){if(!mode||!pair||mode.value!=='quotex_otc')return;try{const r=await fetch('/quotex/current-market',{cache:'no-store',credentials:'same-origin'}),d=await r.json();if(!d.ok||!d.pair)return;const changed=d.pair!==lastSyncedPair;if(changed){let o=Array.from(pair.options).find(x=>x.value===d.pair);if(!o){o=document.createElement('option');o.value=d.pair;o.textContent=d.pair;o.dataset.market='quotex_otc';pair.appendChild(o)}pair.value=d.pair;lastSyncedPair=d.pair;await fetch('/select-market',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},credentials:'same-origin',body:new URLSearchParams({mode:'quotex_otc',pair:d.pair})})}}catch(_){}}sync();setInterval(sync,3000);const s=document.createElement('script');s.src='/static/quotex_real_chart.js';s.defer=true;document.body.appendChild(s);const auto=document.getElementById('auto-toggle');if(auto&&typeof runAuto==='function'&&typeof state!=='undefined'){const schedule=()=>{clearTimeout(state.autoTimer);if(!state.auto)return;const now=Date.now(),next=Math.floor(now/60000+1)*60000;state.autoTimer=setTimeout(()=>{if(!state.auto)return;runAuto();schedule()},Math.max(50,next-now+1500))};auto.onchange=()=>{state.auto=auto.checked;clearTimeout(state.autoTimer);if(state.auto){const st=document.getElementById('auto-status');if(st)st.textContent='AUTO SIGNAL চালু';schedule()}else{const st=document.getElementById('auto-status');if(st)st.textContent='AUTO SIGNAL বন্ধ'}};if(auto.checked)schedule()}})();document.getElementById('performance')?.remove();document.querySelectorAll('[data-scroll="performance"],#performance-toggle').forEach(e=>e.remove());</script>"""
        if "</body>" in html: response.set_data(html.replace("</body>", script + "</body>", 1))
        return response
    return app
