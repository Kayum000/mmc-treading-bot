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
#mtd-open{display:none}
#mtd-menu{position:absolute;right:0;bottom:calc(100% + 8px);z-index:10001;background:#fff;border:1px solid #cbd5e1;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.18);padding:7px}
#mtd-menu[hidden]{display:none}
#mtd-menu button{border:0;border-radius:8px;padding:9px 13px;background:#0f766e;color:#fff;font-weight:800;cursor:pointer;white-space:nowrap}
#mtd-panel{position:absolute;right:0;bottom:calc(100% + 8px);z-index:10002;width:min(92vw,430px);max-height:70vh;overflow:auto;background:#fff;border:1px solid #cbd5e1;border-radius:14px;box-shadow:0 10px 35px rgba(0,0,0,.22);padding:14px;font:600 13px Arial;color:#172033}
#mtd-panel[hidden]{display:none}
#mtd-panel h3{margin:0 0 10px;font-size:15px}.mtd-close{float:right;border:0;background:transparent;font-size:20px;cursor:pointer}
#mtd-actions{display:flex;flex-wrap:wrap;gap:7px}.mtd-action{border:0;border-radius:8px;padding:9px 11px;background:#2563eb;color:#fff;font-weight:800;cursor:pointer}.mtd-action.secondary{background:#475569}
#mtd-list{margin-top:11px;line-height:1.6;word-break:break-word;color:#475569}
</style>
<div id="master-trusted-ui"><button id="mtd-open" type="button" hidden>TRUSTED DEVICES</button><div id="mtd-menu" hidden><button id="mtd-menu-open" type="button">TRUSTED DEVICES</button></div><div id="mtd-panel" hidden><button class="mtd-close" id="mtd-close" type="button">×</button><h3>MASTER / TRUSTED DEVICES</h3><div id="mtd-actions"><button class="mtd-action" id="mtd-add" type="button" hidden>ADD TRUSTED</button><button class="mtd-action" id="mtd-self" type="button" hidden>TRUST THIS DEVICE</button><button class="mtd-action" id="mtd-join" type="button" hidden>JOIN TRUSTED</button></div><div id="mtd-list">Checking…</div></div></div>
<script id="master-trusted-ui-script">(function(){
  const host=document.getElementById('master-trusted-ui'),open=document.getElementById('mtd-open'),menu=document.getElementById('mtd-menu'),menuOpen=document.getElementById('mtd-menu-open'),panel=document.getElementById('mtd-panel'),close=document.getElementById('mtd-close'),add=document.getElementById('mtd-add'),self=document.getElementById('mtd-self'),join=document.getElementById('mtd-join'),list=document.getElementById('mtd-list');
  if(!host||!open||!menu||!menuOpen||!panel)return;
  const KEY='mmc_master_device_id';
  let id=localStorage.getItem(KEY)||'';
  try{if(window.AndroidSignalAlert&&window.AndroidSignalAlert.getDeviceId) id=window.AndroidSignalAlert.getDeviceId()||id;}catch(_){ }
  if(!id) id=(crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random());
  localStorage.setItem(KEY,id);
  try{if(window.AndroidSignalAlert&&window.AndroidSignalAlert.setDeviceId)window.AndroidSignalAlert.setDeviceId(id);}catch(_){ }
  function place(){
    const overlay=document.getElementById('master-control-overlay');
    const badge=document.getElementById('master-role-badge');
    if(overlay){
      open.hidden=true;
      if(menu.parentNode!==overlay) overlay.appendChild(menu);
      if(panel.parentNode!==overlay) overlay.appendChild(panel);
      if(open.parentNode!==overlay) overlay.appendChild(open);
      if(badge){
        badge.style.cursor='pointer';
        badge.title='Open Master Panel options';
        if(!badge.dataset.mtdBound){
          badge.dataset.mtdBound='1';
          badge.addEventListener('click',function(){
            if(badge.textContent.indexOf('MASTER / MAIN PANEL')===0){
              menu.hidden=!menu.hidden;
              if(!menu.hidden){panel.hidden=true;refresh();}
            }
          });
        }
      }
      return true;
    }
    return false;
  }
  async function refresh(){
    try{
      const s=await (await fetch('/master/status',{credentials:'same-origin',cache:'no-store'})).json();
      const master=s.role==='MASTER';
      add.hidden=!master; self.hidden=!master;
      if(master){
        join.hidden=true;
        const x=await (await fetch('/master/trusted/list',{credentials:'same-origin',cache:'no-store'})).json();
        list.textContent=(x.devices||[]).map(v=>v.name+' ['+v.device_hash+']').join(' • ')||'No trusted devices';
      }else{
        const t=await (await fetch('/master/trusted/status',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({device_id:id}),cache:'no-store'})).json();
        const trusted=!!t.trusted;
        join.hidden=trusted;
        list.textContent=trusted?'এই ডিভাইসটি Trusted হিসেবে সংরক্ষিত আছে।':'এই ডিভাইসটি এখনো Trusted নয়।';
      }
    }catch(e){list.textContent='Trusted Device status unavailable.';}
  }
  menuOpen.onclick=()=>{menu.hidden=true;panel.hidden=false;refresh()};
  open.onclick=()=>{menu.hidden=true;panel.hidden=false;refresh()};
  close.onclick=()=>panel.hidden=true;
  add.onclick=async()=>{try{const x=await (await fetch('/master/trusted/invite',{method:'POST',credentials:'same-origin'})).json();if(x.code)prompt('এই code-টি অন্য ডিভাইসে দিন। ১০ মিনিট valid এবং একবার ব্যবহারযোগ্য।',x.code);else alert(x.error||'Invite তৈরি হয়নি।');}catch(e){alert('Invite তৈরি করা যায়নি।')}};
  self.onclick=async()=>{const name=prompt('এই ডিভাইসের নাম:','Main Device');if(name===null)return;try{const x=await (await fetch('/master/trusted/self',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({device_id:id,name:name||'This device'})})).json();alert(x.message||x.error||'Done');refresh();}catch(e){alert('Trusted Device সংরক্ষণ করা যায়নি।')}};
  join.onclick=async()=>{const code=prompt('Master-এর Trusted code দিন:');if(!code)return;const name=prompt('Device name:','My Phone')||'Trusted device';try{const x=await (await fetch('/master/trusted/enroll',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({code:code,device_id:id,name:name})})).json();alert(x.message||x.error||'Done');refresh();}catch(e){alert('Trusted Device যোগ করা যায়নি।')}};
  place();
  new MutationObserver(place).observe(document.documentElement,{childList:true,subtree:true});
  setInterval(()=>{if(!panel.hidden)refresh()},10000);
})();</script>'''
        response.set_data(html.replace("</body>", script + "</body>", 1))
        return response
