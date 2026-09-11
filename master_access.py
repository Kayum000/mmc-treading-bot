"""Master/Viewer control layer with two synchronized Master devices."""
from __future__ import annotations

import hashlib
import hmac
import os
import time

from flask import current_app, jsonify, request, session

from signals.get_signal import get_signal
from performance import record_signal
from master_store import store


def _device_hash(device_id: str) -> str:
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def _is_trusted() -> bool:
    device_id = str(session.get("trusted_device_id") or session.get("master_device_id") or "").strip()
    if not device_id or not store.enabled:
        return False
    return bool(session.get("trusted_device") and store.is_trusted_hash(_device_hash(device_id)))


def _state() -> dict:
    if store.enabled:
        return store.get_state()
    return {"master_device_hash": None, "master_device_hash_2": None, "mode": "", "pair": "", "result": None, "updated_at": 0.0}


def _is_master() -> bool:
    device_id = str(session.get("master_device_id") or "")
    if not session.get("master") or not device_id:
        return False
    current = _device_hash(device_id)
    state = _state()
    return current in {state.get("master_device_hash"), state.get("master_device_hash_2")}


def _claim_master(device_id: str, setup_key: str, recover_slot: int | None = None) -> tuple[bool, str]:
    configured_key = os.getenv("MASTER_SETUP_KEY", "").strip()
    if not configured_key:
        return False, "Master setup is not configured on the server."
    if not device_id:
        return False, "Device ID is required."
    if not hmac.compare_digest(setup_key, configured_key):
        return False, "Invalid Master activation key."
    if recover_slot in (1, 2) and store.enabled:
        ok, message = store.recover_master(_device_hash(device_id), recover_slot)
        if ok:
            session["master"] = True
            session["master_device_id"] = device_id
            session["trusted_device"] = False
            session.pop("trusted_device_id", None)
        return ok, message
    ok, message = store.claim_master(_device_hash(device_id)) if store.enabled else (True, "MASTER device authorized successfully.")
    if not ok:
        return False, message
    session["master"] = True
    session["master_device_id"] = device_id
    session["trusted_device"] = False
    session.pop("trusted_device_id", None)
    return True, message


def _state_payload() -> dict:
    state = _state()
    master = _is_master()
    trusted = (not master) and _is_trusted()
    return {
        "ok": True,
        "role": "MASTER" if master else ("TRUSTED" if trusted else "VIEWER"),
        "trusted": trusted,
        "master_count": int(bool(state.get("master_device_hash"))) + int(bool(state.get("master_device_hash_2"))),
        "pair": state.get("pair", ""),
        "mode": state.get("mode", ""),
        "result": state.get("result"),
        "updated_at": state.get("updated_at", 0.0),
        "storage": "postgres" if store.enabled else "memory-fallback",
    }


def init_master_access(app) -> None:
    @app.route("/master/status", methods=["GET"])
    def master_status():
        return jsonify(_state_payload())

    @app.route("/master/claim", methods=["POST"])
    def master_claim():
        data = request.get_json(silent=True) or request.form
        recover_raw = str(data.get("recover_slot", "")).strip()
        recover_slot = int(recover_raw) if recover_raw in {"1", "2"} else None
        device_id = str(data.get("device_id", "")).strip()
        ok, message = _claim_master(device_id, str(data.get("setup_key", "")).strip(), recover_slot)
        if ok:
            session["master"] = True
            session["master_device_id"] = device_id
        return jsonify({"ok": ok, "message": message, "role": "MASTER" if ok else "VIEWER"}), (200 if ok else 403)

    @app.route("/master/sync-selection", methods=["POST"])
    def master_sync_selection():
        if not _is_master():
            return jsonify({"ok": False, "error": "MASTER authorization required."}), 403
        data = request.get_json(silent=True) or request.form
        mode = str(data.get("mode", "")).strip().lower()
        pair = str(data.get("pair", "")).strip().upper()
        if not mode or not pair:
            return jsonify({"ok": False}), 400
        session["selected_mode"] = mode
        session["selected_pair"] = pair
        return jsonify({"ok": True, "mode": mode, "pair": pair})

    @app.route("/master/signal", methods=["GET"])
    def master_signal():
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
            return jsonify({"ok": True, "result": result, "role": "TRUSTED" if _is_trusted() else "VIEWER"})
        try:
            result = get_signal(pair, mode, automatic=True)
            record_signal(result)
        except Exception as exc:
            current_app.logger.exception("Master signal failed mode=%s pair=%s", mode, pair)
            return jsonify({"ok": False, "error": str(exc)}), 502
        now = time.time()
        if store.enabled:
            store.update_signal(mode, pair, result, now)
        return jsonify({"ok": True, "result": result, "role": "MASTER"})

    @app.before_request
    def _master_guard():
        if request.endpoint in {"master_status", "master_claim", "master_sync_selection"}:
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
#master-role-badge.master{background:#dcfce7;color:#166534}
#master-claim-btn{border:0;border-radius:7px;padding:6px 9px;background:#2563eb;color:#fff;font-weight:800;cursor:pointer}
</style><div id="master-control-overlay"><span id="master-role-badge">Checking…</span><button id="master-claim-btn" type="button" hidden>GET MASTER ACCESS</button></div>
<script>
(()=>{
 const overlay=document.getElementById('master-control-overlay'),badge=document.getElementById('master-role-badge'),claim=document.getElementById('master-claim-btn');
 if(!overlay||!badge||!claim)return;
 const KEY='mmc_master_device_id',SETUP_KEY='mmc_master_setup_key';
 let nativeId='';
 try{if(window.AndroidSignalAlert&&typeof window.AndroidSignalAlert.getDeviceId==='function')nativeId=window.AndroidSignalAlert.getDeviceId()||'';}catch(_){ }
 let id=nativeId||localStorage.getItem(KEY)||'';
 if(!id){id=(crypto.randomUUID?crypto.randomUUID():(Date.now()+'-'+Math.random()));}
 localStorage.setItem(KEY,id);
 try{if(window.AndroidSignalAlert&&typeof window.AndroidSignalAlert.setDeviceId==='function')window.AndroidSignalAlert.setDeviceId(id);}catch(_){ }
 let lastSharedSignalKey='';
 let localSelectionVersion=0;
 let pendingSelection='';
 async function syncMasterSession(mode,pair){try{await fetch('/master/sync-selection',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({mode,pair}),cache:'no-store'});}catch(_){}}
 async function autoClaim(){
   const key=localStorage.getItem(SETUP_KEY)||'';
   if(!key)return false;
   try{
     const r=await fetch('/master/claim',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({device_id:id,setup_key:key}),cache:'no-store'});
     if(r.ok){location.reload();return true;}
   }catch(_){ }
   return false;
 }
 async function persistSelection(mode,pair,version){
   try{
     const body=new URLSearchParams({mode,pair});
     const r=await fetch('/select-market',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body,credentials:'same-origin',cache:'no-store'});
     if(r.ok&&version===localSelectionVersion) pendingSelection='';
     else if(!r.ok&&version===localSelectionVersion) pendingSelection='';
   }catch(_){ }
 }
 function noteLocalSelection(){
   const mode=document.getElementById('mode'),pair=document.getElementById('pair');
   if(!mode||!pair||!mode.value||!pair.value)return;
   localSelectionVersion++;
   pendingSelection=`${mode.value}|${pair.value}`;
   const version=localSelectionVersion;
   setTimeout(()=>persistSelection(mode.value,pair.value,version),80);
 }
 async function status(){try{const r=await fetch('/master/status',{cache:'no-store',credentials:'same-origin'});const d=await r.json();const master=d.role==='MASTER';const trusted=d.role==='TRUSTED'||!!d.trusted;badge.textContent=master?'MASTER / MAIN PANEL':(trusted?'TRUSTED / SECONDARY':'VIEWER / SECONDARY');badge.className=master?'master':'viewer';
   const hasFreeMasterSlot=!master&&!trusted&&d.master_count<2;
   const needsRecovery=!master&&!trusted&&d.master_count>=2;
   claim.hidden=!(hasFreeMasterSlot||needsRecovery);
   claim.textContent=needsRecovery?'RESTORE MASTER':'GET MASTER ACCESS';
   overlay.style.display=(master||trusted||hasFreeMasterSlot||needsRecovery)?'flex':'none';
   const mode=document.getElementById('mode'),pair=document.getElementById('pair');
   if(mode&&pair&&d.pair&&d.mode){
     const central=`${d.mode}|${d.pair}`;
     const local=`${mode.value}|${pair.value}`;
     const shouldApplyCentral=master ? (!pendingSelection || pendingSelection===central || local===central) : true;
     if(shouldApplyCentral){
       mode.value=d.mode;
       Array.from(pair.options).forEach(o=>o.hidden=o.dataset.market&&o.dataset.market!==d.mode);
       pair.value=d.pair;
       mode.disabled=!master;
       pair.disabled=!master;
     }
     if(master)syncMasterSession(d.mode,d.pair);
   }
   if(!master&&d.result&&typeof window.renderResult==='function'){
     const r=d.result;const key=`${r.pair||d.pair||''}|${r.signal||''}|${r.entry_time_utc||d.updated_at||''}`;
     if(key!==lastSharedSignalKey){lastSharedSignalKey=key;window.renderResult(r);if(window.alertForSignal)window.alertForSignal(r);}
   }
   if(!master&&!trusted&&localStorage.getItem(SETUP_KEY))autoClaim();
 }catch(_){overlay.style.display='none'}}
 claim.addEventListener('click',async()=>{
   let key=localStorage.getItem(SETUP_KEY)||prompt('Master activation key:');
   if(!key)return;
   key=key.trim();
   localStorage.setItem(SETUP_KEY,key);
   const full=claim.textContent==='RESTORE MASTER';
   let recoverSlot='';
   if(full){
     recoverSlot=prompt('এই ফোনটি আগে কোন Master slot-এ ছিল?\n1 = MASTER 1\n2 = MASTER 2\n\nভুল slot দিলে সেই slot-এর পুরোনো ডিভাইসটি replace হবে।','2');
     if(recoverSlot!=='1'&&recoverSlot!=='2')return;
     if(!confirm(`MASTER ${recoverSlot} এই ফোনে restore করবেন?`))return;
   }
   try{
     const payload={device_id:id,setup_key:key};
     if(recoverSlot)payload.recover_slot=recoverSlot;
     const r=await fetch('/master/claim',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(payload),cache:'no-store'});
     const d=await r.json();
     if(!r.ok)throw Error(d.message||'Master access failed');
     alert(d.message||'Master access granted.');
     location.reload();
   }catch(e){alert(e.message||'Master access failed')}
 });
 async function sharedSignal(){try{if(typeof window.enableSignalAudio==='function')window.enableSignalAudio();const r=await fetch('/master/signal',{cache:'no-store',credentials:'same-origin'});const d=await r.json();if(r.ok&&d.result&&typeof window.renderResult==='function'){window.renderResult(d.result);if(window.alertForSignal)window.alertForSignal(d.result)}}catch(_) {}}
 const button=document.getElementById('signal-button');if(button){button.addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();sharedSignal()},true)}
 const pairControl=document.getElementById('pair');
 if(pairControl)pairControl.addEventListener('change',()=>noteLocalSelection());
 document.querySelectorAll('.mode-btn').forEach(b=>b.addEventListener('click',()=>setTimeout(noteLocalSelection,100)));
 status();setInterval(status,3000);
})();
</script>'''
        if "</body>" in html:
            html=html.replace("</body>", overlay+"</body>", 1)
            response.set_data(html)
        return response
