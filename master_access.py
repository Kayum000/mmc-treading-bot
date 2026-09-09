"""Master/Viewer control layer for the shared MMC dashboard.

This module is deliberately isolated from the signal strategy. Master lock,
selected pair/mode, and latest signal are persisted in the existing Render
PostgreSQL database when DATABASE_URL is available.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from threading import RLock

from flask import jsonify, request, session

from signals.get_signal import get_signal
from performance import record_signal
from master_store import store

_MASTER_LOCK = RLock()


def _device_hash(device_id: str) -> str:
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def _state() -> dict:
    if store.enabled:
        return store.get_state()
    return {"master_device_hash": None, "mode": "", "pair": "", "result": None, "updated_at": 0.0}


def _is_master() -> bool:
    device_id = str(session.get("master_device_id") or "")
    if not session.get("master") or not device_id:
        return False
    state = _state()
    current = state.get("master_device_hash")
    return bool(current) and hmac.compare_digest(current, _device_hash(device_id))


def _claim_master(device_id: str, setup_key: str) -> tuple[bool, str]:
    configured_key = os.getenv("MASTER_SETUP_KEY", "").strip()
    if not configured_key:
        return False, "Master setup is not configured on the server."
    if not device_id:
        return False, "Device ID is required."
    if not hmac.compare_digest(setup_key, configured_key):
        return False, "Invalid Master activation key."

    ok, message = store.claim_master(_device_hash(device_id)) if store.enabled else (True, "MASTER device locked successfully.")
    if not ok:
        return False, message
    session["master"] = True
    session["master_device_id"] = device_id
    return True, message


def _state_payload() -> dict:
    state = _state()
    return {
        "ok": True,
        "role": "MASTER" if _is_master() else "VIEWER",
        "pair": state.get("pair", ""),
        "mode": state.get("mode", ""),
        "result": state.get("result"),
        "updated_at": state.get("updated_at", 0.0),
        "storage": "postgres" if store.enabled else "memory-fallback",
    }


def init_master_access(app) -> None:
    """Attach Master/Viewer routes and UI to the existing Flask app."""

    @app.route("/master/status", methods=["GET"])
    def master_status():
        return jsonify(_state_payload())

    @app.route("/master/claim", methods=["POST"])
    def master_claim():
        data = request.get_json(silent=True) or request.form
        ok, message = _claim_master(
            str(data.get("device_id", "")).strip(),
            str(data.get("setup_key", "")).strip(),
        )
        return jsonify({"ok": ok, "message": message, "role": "MASTER" if ok else "VIEWER"}), (200 if ok else 403)

    @app.route("/master/signal", methods=["GET"])
    def master_signal():
        """Master generates the signal; viewers only read the shared result."""
        mode = session.get("selected_mode", "").strip().lower()
        pair = session.get("selected_pair", "").strip().upper()
        if not mode or not pair:
            return jsonify({"ok": False, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"}), 400

        if not _is_master():
            state = _state()
            result = state.get("result")
            state_pair = state.get("pair", "")
            state_mode = state.get("mode", "")
            if result is None:
                return jsonify({"ok": False, "error": "MASTER এখনো কোনো signal তৈরি করেনি।"}), 409
            if state_mode != mode or state_pair != pair:
                return jsonify({"ok": False, "error": "MASTER বর্তমানে অন্য pair নির্বাচন করেছে.", "master_pair": state_pair}), 409
            return jsonify({"ok": True, "result": result, "role": "VIEWER"})

        try:
            result = get_signal(pair, mode, automatic=True)
            record_signal(result)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

        now = time.time()
        if store.enabled:
            store.update_signal(mode, pair, result, now)
        return jsonify({"ok": True, "result": result, "role": "MASTER"})

    @app.before_request
    def _master_guard():
        if request.endpoint in {"master_status", "master_claim"}:
            return None
        if not session.get("authenticated"):
            return None
        if request.path == "/auto-signal":
            return master_signal()
        return None

    @app.after_request
    def _master_overlay(response):
        if not (response.content_type or "").startswith("text/html"):
            return response
        html = response.get_data(as_text=True)
        if "id=\"master-control-overlay\"" in html:
            return response
        overlay = r'''<style>
#master-control-overlay{position:fixed;left:10px;bottom:10px;z-index:9999;background:#fff;border:1px solid #cbd5e1;border-radius:10px;box-shadow:0 4px 18px rgba(0,0,0,.12);padding:8px 10px;font:700 12px Arial;color:#172033;display:none;align-items:center;gap:8px}
#master-role-badge{padding:5px 8px;border-radius:7px;background:#eef2f7;color:#475569}
#master-role-badge.master{background:#dcfce7;color:#166534}#master-role-badge.viewer{background:#e2e8f0;color:#334155}
#master-claim-btn{border:0;border-radius:7px;padding:6px 9px;background:#2563eb;color:#fff;font-weight:800;cursor:pointer}
</style><div id="master-control-overlay"><span id="master-role-badge">Checking…</span><button id="master-claim-btn" type="button" hidden>SET AS MASTER</button></div>
<script>
(()=>{
 const overlay=document.getElementById('master-control-overlay'),badge=document.getElementById('master-role-badge'),claim=document.getElementById('master-claim-btn');
 if(!overlay||!badge)return;
 const KEY='mmc_master_device_id'; let id=localStorage.getItem(KEY); if(!id){id=(crypto.randomUUID?crypto.randomUUID():(Date.now()+'-'+Math.random()));localStorage.setItem(KEY,id)}
 let lastSharedSignalKey='';
 async function status(){try{const r=await fetch('/master/status',{cache:'no-store',credentials:'same-origin'});const d=await r.json();const master=d.role==='MASTER';badge.textContent=master?'MASTER / MAIN PANEL':'VIEWER / SECONDARY';badge.className=master?'master':'viewer';claim.hidden=master;overlay.style.display=master?'flex':'none';
   const mode=document.getElementById('mode'),pair=document.getElementById('pair');
   if(mode&&pair){const viewer=!master;mode.disabled=viewer;pair.disabled=viewer;if(viewer&&d.pair){mode.value=d.mode;Array.from(pair.options).forEach(o=>o.hidden=o.dataset.market&&o.dataset.market!==d.mode);pair.value=d.pair;}}
   if(!master&&d.result&&typeof window.renderResult==='function'){
     const r=d.result;const key=`${r.pair||d.pair||''}|${r.signal||''}|${r.entry_time_utc||d.updated_at||''}`;
     if(key!==lastSharedSignalKey){lastSharedSignalKey=key;window.renderResult(r);if(window.alertForSignal)window.alertForSignal(r);}
   }
 }catch(_){overlay.style.display='none'}}
 claim.addEventListener('click',async()=>{const key=prompt('Master activation key:');if(!key)return;try{const r=await fetch('/master/claim',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({device_id:id,setup_key:key})});const d=await r.json();if(!r.ok)throw Error(d.message||'Master claim failed');alert(d.message);location.reload()}catch(e){alert(e.message||'Master claim failed')}});
 async function sharedSignal(){try{if(typeof window.enableSignalAudio==='function')window.enableSignalAudio();const r=await fetch('/master/signal',{cache:'no-store',credentials:'same-origin'});const d=await r.json();if(r.ok&&d.result&&typeof window.renderResult==='function'){window.renderResult(d.result);if(window.alertForSignal)window.alertForSignal(d.result)}}catch(_) {}}
 const button=document.getElementById('signal-button');if(button){button.addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();sharedSignal()},true)}
 status();setInterval(status,3000);
})();
</script>'''
        if "</body>" in html:
            html=html.replace("</body>", overlay+"</body>", 1)
            response.set_data(html)
        return response
