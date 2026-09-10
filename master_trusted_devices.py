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
        script = """<div id='master-trusted-ui' style='position:fixed;right:10px;bottom:10px;z-index:10001;background:#fff;border:1px solid #cbd5e1;border-radius:10px;padding:8px;box-shadow:0 3px 15px #0002;font:700 12px Arial;display:none'><b id='mtd-badge'>TRUSTED</b> <button id='mtd-add' hidden>ADD TRUSTED</button> <button id='mtd-join' hidden>JOIN TRUSTED</button><div id='mtd-list'></div></div><script id='master-trusted-ui'>(function(){var u=document.getElementById('master-trusted-ui'),a=document.getElementById('mtd-add'),j=document.getElementById('mtd-join'),b=document.getElementById('mtd-badge'),l=document.getElementById('mtd-list'),K='mmc_master_device_id',id=localStorage.getItem(K)||'';if(!id){id=(crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random());localStorage.setItem(K,id)}async function refresh(){try{var s=await fetch('/master/status',{credentials:'same-origin',cache:'no-store'}),d=await s.json(),m=d.role==='MASTER';u.style.display='block';a.hidden=!m;b.textContent=m?'MASTER / TRUSTED DEVICES':'VIEWER';if(!m){var t=await (await fetch('/master/trusted/status',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({device_id:id})})).json();j.hidden=!!t.trusted;b.textContent=t.trusted?'TRUSTED DEVICE':'VIEWER'}else{j.hidden=true;var x=await (await fetch('/master/trusted/list',{credentials:'same-origin'})).json();l.textContent=(x.devices||[]).map(function(v){return v.name+' ['+v.device_hash+']'}).join(' • ')||'No trusted devices'}}catch(e){}}a.onclick=async function(){var x=await (await fetch('/master/trusted/invite',{method:'POST',credentials:'same-origin'})).json();if(x.code)prompt('এই code-টি trusted করতে চান এমন ডিভাইসে দিন। ১০ মিনিট valid এবং একবার ব্যবহারযোগ্য।',x.code)};j.onclick=async function(){var c=prompt('Master-এর Trusted code দিন:');if(!c)return;var n=prompt('Device name:','My Phone')||'Trusted device';var x=await (await fetch('/master/trusted/enroll',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({code:c,device_id:id,name:n})})).json();alert(x.message||x.error||'Done');refresh()};refresh();setInterval(refresh,10000)})();</script>"""
        response.set_data(html.replace("</body>", script + "</body>", 1))
        return response
