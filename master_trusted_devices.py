from __future__ import annotations

import hashlib
import secrets
import time

from flask import jsonify, request, session

from master_store import store


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_master() -> bool:
    device_id = str(session.get("master_device_id") or "").strip()
    return bool(device_id and session.get("master") and store.enabled and store.is_master_hash(_hash(device_id)))


def init_master_trusted_devices(app) -> None:
    @app.route("/master/trusted/status", methods=["POST"])
    def trusted_status():
        if not session.get("authenticated"):
            return jsonify({"ok": False}), 401
        data = request.get_json(silent=True) or {}
        device_id = str(data.get("device_id", "")).strip()
        if not device_id:
            return jsonify({"ok": False, "error": "Device ID required."}), 400
        trusted = store.is_trusted_hash(_hash(device_id)) if store.enabled else False
        if trusted:
            session["trusted_device"] = True
            session["trusted_device_id"] = device_id
        return jsonify({"ok": True, "trusted": trusted, "role": "TRUSTED" if trusted else ("MASTER" if _is_master() else "VIEWER")})

    @app.route("/master/trusted/invite", methods=["POST"])
    def trusted_invite():
        if not _is_master():
            return jsonify({"ok": False, "error": "MASTER authorization required."}), 403
        code = secrets.token_hex(5).upper()
        ok, message = store.create_trusted_invite(_hash(code), time.time() + 600)
        if not ok:
            return jsonify({"ok": False, "error": message}), 500
        return jsonify({"ok": True, "code": code, "expires_in": 600})

    @app.route("/master/trusted/self", methods=["POST"])
    def trusted_self():
        """Allow the currently authorized Master device to also be recorded as trusted."""
        if not _is_master():
            return jsonify({"ok": False, "error": "MASTER authorization required."}), 403
        data = request.get_json(silent=True) or {}
        device_id = str(data.get("device_id", "")).strip() or str(session.get("master_device_id") or "").strip()
        name = str(data.get("name", "This device")).strip() or "This device"
        if not device_id:
            return jsonify({"ok": False, "error": "Device ID required."}), 400
        ok, message = store.add_trusted_device(_hash(device_id), name)
        if ok:
            session["trusted_device"] = True
            session["trusted_device_id"] = device_id
        return jsonify({"ok": ok, "message": message}), (200 if ok else 500)

    @app.route("/master/trusted/enroll", methods=["POST"])
    def trusted_enroll():
        if not session.get("authenticated"):
            return jsonify({"ok": False, "error": "Login required."}), 401
        data = request.get_json(silent=True) or request.form
        code = str(data.get("code", "")).strip().upper()
        device_id = str(data.get("device_id", "")).strip()
        name = str(data.get("name", "Trusted device")).strip() or "Trusted device"
        if not code or not device_id:
            return jsonify({"ok": False, "error": "Code and device ID are required."}), 400
        ok, message = store.consume_trusted_invite(_hash(code), _hash(device_id), name)
        if ok:
            session["trusted_device"] = True
            session["trusted_device_id"] = device_id
        return jsonify({"ok": ok, "message": message}), (200 if ok else 403)

    @app.route("/master/trusted/list", methods=["GET"])
    def trusted_list():
        if not _is_master():
            return jsonify({"ok": False, "error": "MASTER authorization required."}), 403
        devices = store.list_trusted_devices() if store.enabled else []
        return jsonify({"ok": True, "devices": [{"name": x.get("name", "Trusted device"), "device_hash": x.get("device_hash", "")[:12] + "…"} for x in devices]})

    @app.route("/master/trusted/remove", methods=["POST"])
    def trusted_remove():
        if not _is_master():
            return jsonify({"ok": False, "error": "MASTER authorization required."}), 403
        data = request.get_json(silent=True) or {}
        device_hash = str(data.get("device_hash", "")).strip()
        if not device_hash:
            return jsonify({"ok": False, "error": "Device hash is required."}), 400
        ok, message = store.remove_trusted_device(device_hash)
        return jsonify({"ok": ok, "message": message}), (200 if ok else 404)

    @app.after_request
    def trusted_ui(response):
        if not (response.content_type or "").startswith("text/html"):
            return response
        html = response.get_data(as_text=True)
        if 'id="master-trusted-ui"' in html or "</body>" not in html:
            return response
        script = r'''<style>
#master-trusted-ui{display:none}
#mtd-panel{position:fixed;left:50%;bottom:64px;transform:translateX(-50%);z-index:10002;width:min(92vw,420px);background:#fff;border:1px solid #cbd5e1;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.2);padding:14px;font:600 13px Arial;color:#172033}
#mtd-panel[hidden]{display:none}
#mtd-panel h3{margin:0 0 10px;font-size:15px}
#mtd-actions{display:flex;flex-wrap:wrap;gap:7px}
#mtd-actions button{border:0;border-radius:8px;padding:8px 10px;background:#2563eb;color:#fff;font-weight:800;cursor:pointer}
#mtd-actions button.secondary{background:#475569}
#mtd-list{margin-top:10px;line-height:1.6;word-break:break-word;color:#475569}
#mtd-close{float:right;border:0;background:transparent;font-size:18px;cursor:pointer}
#mtd-open{border:0;border-radius:7px;padding:6px 9px;background:#0f766e;color:#fff;font-weight:800;cursor:pointer}
</style>
<div id="master-trusted-ui" aria-hidden="true">
  <button id="mtd-open" type="button" hidden>TRUSTED DEVICES</button>
  <div id="mtd-panel" hidden>
    <button id="mtd-close" type="button">×</button>
    <h3>MASTER / TRUSTED DEVICES</h3>
    <div id="mtd-actions">
      <button id="mtd-add" type="button" hidden>ADD TRUSTED</button>
      <button id="mtd-self" type="button" hidden>TRUST THIS DEVICE</button>
      <button id="mtd-join" type="button" hidden>JOIN TRUSTED</button>
    </div>
    <div id="mtd-list">Loading…</div>
  </div>
</div>
<script id="master-trusted-ui-script">(function(){
  var host=document.getElementById('master-trusted-ui'),open=document.getElementById('mtd-open'),panel=document.getElementById('mtd-panel'),close=document.getElementById('mtd-close'),add=document.getElementById('mtd-add'),self=document.getElementById('mtd-self'),join=document.getElementById('mtd-join'),list=document.getElementById('mtd-list');
  if(!host||!open||!panel)return;
  var K='mmc_master_device_id',id=localStorage.getItem(K)||'';
  if(!id){id=(crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random());localStorage.setItem(K,id)}
  function bindToMasterPanel(){
    var badge=document.getElementById('master-role-badge');
    if(!badge||open.parentNode===badge.parentNode)return false;
    badge.parentNode.insertBefore(open,badge.nextSibling);
    open.hidden=false;
    return true;
  }
  function toggle(){panel.hidden=!panel.hidden;if(!panel.hidden)refresh();}
  open.onclick=toggle;close.onclick=function(){panel.hidden=true};
  async function refresh(){
    try{
      var s=await (await fetch('/master/status',{credentials:'same-origin',cache:'no-store'})).json(),master=s.role==='MASTER';
      add.hidden=!master;self.hidden=!master;join.hidden=master;
      if(master){
        var x=await (await fetch('/master/trusted/list',{credentials:'same-origin',cache:'no-store'})).json();
        list.textContent=(x.devices||[]).map(function(v){return v.name+' ['+v.device_hash+']'}).join(' • ')||'No trusted devices';
      }else{
        var t=await (await fetch('/master/trusted/status',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({device_id:id})})).json();
        list.textContent=t.trusted?'এই ডিভাইসটি Trusted হিসেবে সংরক্ষিত আছে।':'এই ডিভাইসটি এখনো Trusted নয়।';
        join.hidden=!!t.trusted;
      }
    }catch(e){list.textContent='Trusted Device status unavailable.'}
  }
  add.onclick=async function(){
    var x=await (await fetch('/master/trusted/invite',{method:'POST',credentials:'same-origin'})).json();
    if(x.code)prompt('এই code-টি অন্য ডিভাইসে দিন। ১০ মিনিট valid এবং একবার ব্যবহারযোগ্য।',x.code); else alert(x.error||'Invite তৈরি হয়নি।');
  };
  self.onclick=async function(){
    var name=prompt('এই ডিভাইসের নাম:','My Phone / Main Device');if(name===null)return;
    var x=await (await fetch('/master/trusted/self',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({device_id:id,name:name||'This device'})})).json();
    alert(x.message||x.error||'Done');refresh();
  };
  join.onclick=async function(){
    var c=prompt('Master-এর Trusted code দিন:');if(!c)return;
    var n=prompt('Device name:','My Phone')||'Trusted device';
    var x=await (await fetch('/master/trusted/enroll',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({code:c,device_id:id,name:n})})).json();
    alert(x.message||x.error||'Done');refresh();
  };
  bindToMasterPanel();
  var mo=new MutationObserver(function(){bindToMasterPanel()});
  mo.observe(document.documentElement,{childList:true,subtree:true});
  setInterval(function(){if(!panel.hidden)refresh()},10000);
})();</script>'''
        response.set_data(html.replace("</body>", script + "</body>", 1))
        return response
