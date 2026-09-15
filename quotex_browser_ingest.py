"""Authenticated ingest endpoint for the local Quotex browser collector.

The endpoint accepts candle data only. It never accepts or stores a Quotex
SSID/session token and it never places orders.
"""
from __future__ import annotations

import hmac
import os
import time
import threading
from flask import jsonify, request, session

from data.quotex_otc import ingest_local_candles, local_stream_status, local_active_asset
from data.otc_markets import display_for_asset, OTC_DISPLAY_PAIRS
from signals.get_signal import get_signal
from performance import record_signal

_OTC_MASTER_ENABLED = True
_OTC_MASTER_LOCK = threading.Lock()


def otc_master_enabled() -> bool:
    with _OTC_MASTER_LOCK:
        return _OTC_MASTER_ENABLED


def _set_otc_master(enabled: bool) -> bool:
    global _OTC_MASTER_ENABLED
    with _OTC_MASTER_LOCK:
        _OTC_MASTER_ENABLED = bool(enabled)
    return _OTC_MASTER_ENABLED


def _collector_secret_valid() -> bool:
    expected = (os.getenv("QUOTEX_INGEST_SECRET") or "").strip()
    supplied = (request.headers.get("X-MMC-Quotex-Key") or request.args.get("key") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))


def init_quotex_browser_ingest(app):
    def allow_collector_endpoint():
        if request.endpoint in {"quotex_ingest", "quotex_stream_status", "quotex_current_market"} and _collector_secret_valid():
            session["authenticated"] = True
        return None

    app.before_request_funcs.setdefault(None, []).insert(0, allow_collector_endpoint)

    @app.route("/quotex/master", methods=["GET", "POST"])
    def quotex_master():
        if request.method == "POST":
            supplied = (request.headers.get("X-MMC-Quotex-Key") or request.args.get("key") or "").strip()
            if not _collector_secret_valid() and supplied:
                return jsonify({"ok": False, "error": "Invalid ingest key."}), 401
            raw = request.form.get("enabled")
            if raw is None and request.is_json:
                raw = (request.get_json(silent=True) or {}).get("enabled")
            enabled = str(raw).strip().lower() in {"1", "true", "on", "yes", "enabled"}
            if raw is None:
                return jsonify({"ok": False, "error": "enabled is required."}), 400
            _set_otc_master(enabled)
        return jsonify({"ok": True, "enabled": otc_master_enabled(), "mode": "quotex_otc"})

    @app.route("/quotex/ingest", methods=["POST"])
    def quotex_ingest():
        expected = (os.getenv("QUOTEX_INGEST_SECRET") or "").strip()
        supplied = (request.headers.get("X-MMC-Quotex-Key") or request.args.get("key") or "").strip()
        if not expected:
            return jsonify({"ok": False, "error": "QUOTEX_INGEST_SECRET is not configured on the server."}), 503
        if not supplied or not hmac.compare_digest(supplied, expected):
            return jsonify({"ok": False, "error": "Invalid ingest key."}), 401
        if not request.is_json:
            return jsonify({"ok": False, "error": "JSON body required."}), 415
        if not otc_master_enabled():
            return jsonify({"ok": True, "enabled": False, "accepted": 0, "status": local_stream_status()}), 200
        payload = request.get_json(silent=True) or {}
        sent_at = payload.get("sent_at")
        try:
            if sent_at is not None and abs(time.time() - float(sent_at)) > 30:
                return jsonify({"ok": False, "error": "Stale collector payload."}), 408
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Invalid sent_at."}), 400
        accepted = ingest_local_candles(payload)
        if not accepted:
            return jsonify({"ok": False, "error": "No supported closed candle data found."}), 422
        return jsonify({"ok": True, "accepted": accepted, "status": local_stream_status()})

    @app.route("/quotex/stream-status", methods=["GET"])
    def quotex_stream_status():
        result = local_stream_status()
        result["master_otc_enabled"] = otc_master_enabled()
        return jsonify(result)

    @app.route("/quotex/current-market", methods=["GET"])
    def quotex_current_market():
        asset = local_active_asset()
        return jsonify({
            "ok": bool(asset) and otc_master_enabled(),
            "market_mode": "quotex_otc",
            "asset": asset,
            "pair": display_for_asset(asset) if asset and otc_master_enabled() else None,
            "master_otc_enabled": otc_master_enabled(),
            "source": "Quotex local screen collector",
        })

    original_select_market = app.view_functions.get("select_market")
    original_auto_signal = app.view_functions.get("auto_signal")

    def select_market_dynamic():
        mode = request.form.get("mode", "").strip().lower()
        pair = request.form.get("pair", "").strip().upper()
        if mode == "quotex_otc":
            if not otc_master_enabled():
                return jsonify({"ok": False, "error": "OTC MASTER switch is OFF."}), 423
            detected = local_active_asset()
            detected_pair = display_for_asset(detected) if detected else None
            if detected_pair:
                pair = detected_pair
            if pair not in OTC_DISPLAY_PAIRS:
                return jsonify({"ok": False, "error": "বর্তমান OTC মার্কেট এখনো শনাক্ত হয়নি।"}), 409
            session["selected_mode"] = "quotex_otc"
            session["selected_pair"] = pair
            return jsonify({"ok": True, "mode": "quotex_otc", "pair": pair, "automatic": True})
        if original_select_market is not None:
            return original_select_market()
        return jsonify({"ok": False, "error": "Market selector unavailable."}), 500

    def auto_signal_dynamic():
        mode = session.get("selected_mode", "").strip().lower()
        if mode == "quotex_otc":
            if not otc_master_enabled():
                return jsonify({"ok": False, "error": "OTC MASTER switch is OFF."}), 423
            asset = local_active_asset()
            pair = display_for_asset(asset) if asset else None
            if not pair:
                return jsonify({"ok": False, "error": "বর্তমান Quotex OTC মার্কেট শনাক্ত হয়নি।"}), 409
            session["selected_mode"] = "quotex_otc"
            session["selected_pair"] = pair
            try:
                result = get_signal(pair, "quotex_otc", automatic=True)
                record_signal(result)
                return jsonify({"ok": True, "result": result})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 502
        if original_auto_signal is not None:
            return original_auto_signal()
        return jsonify({"ok": False, "error": "Auto signal unavailable."}), 500

    if original_select_market is not None:
        app.view_functions["select_market"] = select_market_dynamic
    if original_auto_signal is not None:
        app.view_functions["auto_signal"] = auto_signal_dynamic

    @app.after_request
    def inject_otc_market_sync(response):
        if not (response.content_type or "").startswith("text/html"):
            return response
        html = response.get_data(as_text=True)
        if "id=\"pair\"" not in html or "QUOTEX_AUTO_MARKET_SYNC" in html:
            return response
        script = '''<script id="QUOTEX_AUTO_MARKET_SYNC">(()=>{const mode=document.getElementById('mode'),pair=document.getElementById('pair'),button=document.getElementById('signal-button');if(!mode||!pair)return;let busy=false;async function sync(){if(busy||mode.value!=='quotex_otc')return;busy=true;try{const r=await fetch('/quotex/current-market',{cache:'no-store',credentials:'same-origin'}),d=await r.json();if(d.ok&&d.pair){let o=Array.from(pair.options).find(x=>x.value===d.pair);if(!o){o=document.createElement('option');o.value=d.pair;o.textContent=d.pair;o.dataset.market='quotex_otc';pair.appendChild(o)}Array.from(pair.options).forEach(x=>x.hidden=x.dataset.market&&x.dataset.market!==mode.value);pair.value=d.pair;pair.dispatchEvent(new Event('change',{bubbles:true}));if(button)button.disabled=false;await fetch('/select-market',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},credentials:'same-origin',body:new URLSearchParams({mode:'quotex_otc',pair:d.pair})})}}catch(_){ }finally{busy=false}}document.querySelectorAll('.mode-btn').forEach(b=>b.addEventListener('click',()=>setTimeout(sync,150)));sync();setInterval(sync,1500)})();</script>'''
        marker = '</body>'
        if marker in html:
            html = html.replace(marker, script + marker, 1)
            response.set_data(html)
        return response

    return app
