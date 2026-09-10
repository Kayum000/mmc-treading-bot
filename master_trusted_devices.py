from __future__ import annotations
import hashlib, secrets, time
from flask import jsonify, request, session
from master_store import store

def dh(v): return hashlib.sha256(v.encode()).hexdigest()
def master():
    d=str(session.get('master_device_id') or '').strip()
    return bool(d and session.get('master') and store.enabled and store.is_master_hash(dh(d)))

def init_master_trusted_devices(app):
    @app.route('/master/trusted/status', methods=['POST'])
    def trusted_status():
        if not session.get('authenticated'): return jsonify({'ok':False}),401
        d=str((request.get_json(silent=True) or {}).get('device_id','')).strip()
        if not d: return jsonify({'ok':False,'error':'Device ID required.'}),400
        ok=store.is_trusted_hash(dh(d)) if store.enabled else False
        if ok: session['trusted_device']=True; session['trusted_device_id']=d
        return jsonify({'ok':True,'trusted':ok})

    @app.route('/master/trusted/invite', methods=['POST'])
    def trusted_invite():
        if not master(): return jsonify({'ok':False,'error':'MASTER authorization required.'}),403
        code=secrets.token_hex(5).upper(); store.create_trusted_invite(dh(code),time.time()+600)
        return jsonify({'ok':True,'code':code,'expires_in':600})

    @app.route('/master/trusted/enroll', methods=['POST'])
    def trusted_enroll():
        if not session.get('authenticated'): return jsonify({'ok':False,'error':'Login required.'}),401
        data=request.get_json(silent=True) or request.form; code=str(data.get('code','')).strip().upper(); d=str(data.get('device_id','')).strip(); name=str(data.get('name','Trusted device')).strip()
        if not code or not d: return jsonify({'ok':False,'error':'Code and device ID are required.'}),400
        ok,msg=store.consume_trusted_invite(dh(code),dh(d),name)
        if ok: session['trusted_device']=True; session['trusted_device_id']=d
        return jsonify({'ok':ok,'message':msg}),200 if ok else 403

    @app.route('/master/trusted/list')
    def trusted_list():
        if not master(): return jsonify({'ok':False,'error':'MASTER authorization required.'}),403
        return jsonify({'ok':True,'devices':[{'name':x.get('name','Trusted device'),'id':x.get('device_hash','')[:12]} for x in store.list_trusted_devices()]})

    @app.route('/master/trusted/remove', methods=['POST'])
    def trusted_remove():
        if not master(): return jsonify({'ok':False,'error':'MASTER authorization required.'}),403
        d=str((request.get_json(silent=True) or {}).get('device_hash','')).strip(); ok,msg=store.remove_trusted_device(d)
        return jsonify({'ok':ok,'message':msg}),200 if ok else 404

    @app.after_request
    def trusted_ui(response):
        if not (response.content_type or '').startswith('text/html') or 'master-trusted-ui' in response.get_data(as_text=True): return response
        html=response.get_data(as_text=True)
        if '</body>' not in html: return response
        ui='''<div id="master-trusted-ui" style="position:fixed;right:10px;bottom:10px;z-index:10001;background:#fff;border:1px solid #cbd5e1;border-radius:10px;padding:8px;box-shadow:0 3px 15px #0002;font:700 12px Arial;display:none"><b id="mtd-badge">TRUSTED</b> <button id="mtd-add" hidden>ADD TRUSTED</button> <button id="mtd-join" hidden>JOIN TRUSTED</button><div id="mtd-list"></div></div><script id="master-trusted-ui">(()=>{const u=document.getElementById('master-trusted-ui'),a=document.getElementById('mtd-add'),j=document.getElementById('mtd-join'),b=document.getElementById('mtd-badge'),l=document.getElementById('mtd-list'),K='mmc_master_device_id';let id=localStorage.getItem(K)||'';if(!id){id=crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random();localStorage.setItem(K,id)}async function s(){try{let d=await (await fetch('/master/status',{credentials:'same-origin',cache:'no-store'})).json(),m=d.role==='MASTER';u.style.display='block';a.hidden=!m;j.hidden=m;b.textContent=m?'MASTER / TRUSTED DEVICES':'VIEWER';if(!m){let t=await (await fetch('/master/trusted/status',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({device_id:id})})).json();if(t.trusted){b.textContent='TRUSTED DEVICE';j.hidden=true}else j.hidden=false}if(m){let x=await (await fetch('/master/trusted/list',{credentials:'same-origin'})).json();l.textContent=(x.devices||[]).map(v=>v.name+' ['+v.id+']').join(' • ')||'No trusted devices'}}catch(e){}}a.onclick=async()=>{let x=await (await fetch('/master/trusted/invite',{method:'POST',credentials:'same-origin'})).json();if(x.code)prompt('এই code-টি অন্য লগইন করা ডিভাইসে দিন। ১০ মিনিট valid, একবার ব্যবহারযোগ্য।',x.code)};j.onclick=async()=>{let c=prompt('Master-এর Trusted code দিন:');if(!c)return;let n=prompt('Device name:','My Phone')||'Trusted device';let x=await (await fetch('/master/trusted/enroll',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({code:c,device_id:id,name:n})})).json();alert(x.message||x.error||'Done');s()};s();setInterval(s,10000)})();</script>'''
        response.set_data(html.replace('</body>',ui+'</body>',1));return response
'''
