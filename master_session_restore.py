"""Restore a previously authorized Master session from its stable device ID."""
from __future__ import annotations

import hashlib
import re

from flask import jsonify, request, session

from master_store import store


def _device_hash(device_id: str) -> str:
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def _delete_legacy_dashboard_duplicates(html: str) -> str:
    """Delete legacy dashboard fragments instead of hiding duplicate UI."""
    patterns = (
        r'<[^>]*\bid=["\']performance-compact["\'][^>]*>.*?</[^>]+>',
        r'<[^>]*\bid=["\']market-status-panel["\'][^>]*>.*?</[^>]+>',
    )
    cleaned = html
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r'<[^>]*\bclass=["\'][^"\']*\bchart-bar\b[^"\']*["\'][^>]*>.*?</[^>]+>', "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned


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
        html = _delete_legacy_dashboard_duplicates(html)
        if "id=\"master-session-restore\"" in html:
            response.set_data(html)
            return response
        script = r'''<script id="master-session-restore">(()=>{try{const id=localStorage.getItem('mmc_master_device_id')||'';if(id)fetch('/master/restore-session',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({device_id:id}),cache:'no-store'}).then(r=>r.ok?r.json():null).then(d=>{if(d&&d.ok&&!document.cookie.includes('mmc_master_restored=1')){document.cookie='mmc_master_restored=1; path=/; max-age=60';location.reload()}}).catch(()=>{})}catch(_){}})();
(()=>{const esc=v=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));const bdTime=v=>{if(!v)return '—';try{const d=new Date(v);return new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Dhaka',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:true}).format(d)+' BD'}catch(_){return String(v)}};const render=async()=>{const t=document.getElementById('modal-title');const x=document.getElementById('modal-extra');if(!t||!x||t.textContent.trim()!=='Performance 24H'||x.dataset.mmcPerfControls==='1')return;x.dataset.mmcPerfControls='1';const load=async()=>{const r=await fetch('/performance',{credentials:'same-origin',cache:'no-store'});const d=await r.json();if(!r.ok||d.ok===false)throw Error(d.error||'Performance unavailable');const rows=d.history||[];const wins=rows.filter(v=>String(v.result||'').toUpperCase()==='WIN').length;const losses=rows.filter(v=>String(v.result||'').toUpperCase()==='LOSS').length;x.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px"><div style="display:flex;gap:6px;flex-wrap:wrap;font-size:11px"><span style="padding:5px 8px;border:1px solid #174d39;border-radius:7px;color:#7dffbd;background:rgba(0,255,150,.06)">WIN <b>${wins}</b></span><span style="padding:5px 8px;border:1px solid #5a2730;border-radius:7px;color:#ff9aa7;background:rgba(255,70,90,.06)">LOSS <b>${losses}</b></span><span style="padding:5px 8px;border:1px solid #113653;border-radius:7px;color:#b8cbe1">TOTAL <b>${rows.length}</b></span></div><div style="display:flex;gap:6px"><button type="button" id="mmc-perf-refresh" class="mini-btn">↻ Refresh</button><button type="button" id="mmc-perf-clear" class="mini-btn">Clear</button></div></div><div style="display:grid;gap:5px;max-height:260px;overflow:auto">${rows.length?rows.map(v=>`<div style="display:grid;grid-template-columns:1fr .65fr .9fr .9fr 1.5fr;gap:6px;padding:7px;border:1px solid #113653;border-radius:7px;color:#b8cbe1;font-size:10px"><b style="color:#eaf3fc">${esc(v.pair)}</b><span>${esc(v.signal)}</span><span>${esc(v.result)}</span><span>${v.entry_price==null?'—':esc(v.entry_price)}</span><span><b style="display:block;color:#eaf3fc">Signal Time</b>${bdTime(v.signal_time_utc)}</span></div>`).join(''):'<div style="padding:10px;color:#91a8c0">No confirmed results in the last 24 hours.</div>'}</div>`;document.getElementById('mmc-perf-refresh')?.addEventListener('click',load);document.getElementById('mmc-perf-clear')?.addEventListener('click',async()=>{if(!confirm('Clear performance history?'))return;const r=await fetch('/performance',{method:'POST',credentials:'same-origin',headers:{'Accept':'application/json'},cache:'no-store'});const d=await r.json();if(!r.ok||d.ok===false)throw Error(d.error||'Unable to clear performance history');await load()})};try{await load()}catch(e){x.innerHTML=`<div style="padding:10px;color:#ff9aa7">${esc(e.message||e)}</div>`}};const m=document.getElementById('modal');if(!m)return;new MutationObserver(render).observe(m,{attributes:true,childList:true,subtree:true});render()})();</script>'''
        if "</body>" in html:
            html = html.replace("</body>", script + "</body>", 1)
        response.set_data(html)
        return response
