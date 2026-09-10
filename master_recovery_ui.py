"""Small UI-only recovery helper for a Master device that lost its browser identity."""
from __future__ import annotations


def init_master_recovery_ui(app) -> None:
    @app.after_request
    def _master_recovery_script(response):
        if not (response.content_type or "").startswith("text/html"):
            return response
        html = response.get_data(as_text=True)
        if 'id="master-recovery-ui"' in html:
            return response
        script = r'''<script id="master-recovery-ui">(()=>{
  const setup=()=>{
    if(!/Windows NT/i.test(navigator.userAgent||'')) return;
    const overlay=document.getElementById('master-control-overlay');
    const badge=document.getElementById('master-role-badge');
    const claim=document.getElementById('master-claim-btn');
    if(!overlay||!badge||!claim)return;
    fetch('/master/status',{cache:'no-store',credentials:'same-origin'}).then(r=>r.json()).then(d=>{
      if(d.role==='MASTER'||d.master_count<2)return;
      overlay.style.display='flex';
      badge.textContent='MASTER RECOVERY';
      badge.className='viewer';
      claim.hidden=false;
      claim.textContent='RESTORE MASTER';
      claim.onclick=async(e)=>{
        e.preventDefault();e.stopImmediatePropagation();
        const slot=prompt('এই ল্যাপটপটি আগে কোন Master slot-এ ছিল?\n1 = MASTER 1\n2 = MASTER 2\n\nভুল slot দিলে অন্য Master ডিভাইসটি replace হবে।','2');
        if(slot!=='1'&&slot!=='2')return;
        const key=prompt('Master activation key:');
        if(!key)return;
        try{
          const id=localStorage.getItem('mmc_master_device_id')||'';
          const r=await fetch('/master/claim',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({device_id:id,setup_key:key.trim(),recover_slot:slot}),cache:'no-store'});
          const x=await r.json();
          if(!r.ok)throw Error(x.message||'Master recovery failed');
          alert(x.message||'Master restored successfully.');
          location.reload();
        }catch(err){alert(err.message||'Master recovery failed');}
      };
    }).catch(()=>{});
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup,{once:true});else setup();
})();</script>'''
        if "</body>" in html:
            response.set_data(html.replace("</body>", script + "</body>", 1))
        return response
'''
