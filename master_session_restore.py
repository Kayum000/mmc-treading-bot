"""Restore a previously authorized Master session from its stable device ID."""
from __future__ import annotations

from flask import jsonify, request, session

from master_store import store


def _device_hash(device_id: str) -> str:
    import hashlib
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def init_master_session_restore(app) -> None:
    @app.route("/master/restore-session", methods=["POST"])
    def master_restore_session():
        if not session.get("authenticated"):
            return jsonify({"ok": False}), 401
        device_id = str((request.get_json(silent=True) or {}).get("device_id", "")).strip()
        if not device_id or not store.enabled:
            return jsonify({"ok": False}), 404
        state = store.get_state()
        if _device_hash(device_id) in {state.get("master_device_hash"), state.get("master_device_hash_2")}:
            session["master"] = True
            session["master_device_id"] = device_id
            return jsonify({"ok": True, "role": "MASTER"})
        return jsonify({"ok": False, "role": "VIEWER"}), 403

    @app.after_request
    def _restore_script(response):
        if not (response.content_type or "").startswith("text/html"):
            return response
        html = response.get_data(as_text=True)
        if "id=\"master-session-restore\"" in html:
            return response
        script = r'''<script id="master-session-restore">(()=>{try{const id=localStorage.getItem('mmc_master_device_id')||'';if(!id)return;fetch('/master/restore-session',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({device_id:id}),cache:'no-store'}).then(r=>r.ok?r.json():null).then(d=>{if(d&&d.ok&&!document.cookie.includes('mmc_master_restored=1')){document.cookie='mmc_master_restored=1; path=/; max-age=60';location.reload()}}).catch(()=>{})}catch(_){}})();</script>'''
        if "</body>" in html:
            response.set_data(html.replace("</body>", script + "</body>", 1))
        return response
