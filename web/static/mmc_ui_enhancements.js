(()=>{
  const KEY='mmc_theme_color';
  const SOUND_KEY='mmc_signal_sound';
  const themes={
    blue:{a:'#1261c5',b:'#08b887',c:'#58b8f6'},
    cyan:{a:'#0891b2',b:'#06b6d4',c:'#67e8f9'},
    purple:{a:'#6d28d9',b:'#8b5cf6',c:'#c4b5fd'},
    green:{a:'#15803d',b:'#22c55e',c:'#86efac'},
    orange:{a:'#c2410c',b:'#f97316',c:'#fdba74'}
  };
  function applyTheme(name){
    const t=themes[name]||themes.blue;
    let s=document.getElementById('mmc-theme-style');
    if(!s){s=document.createElement('style');s.id='mmc-theme-style';document.head.appendChild(s)}
    s.textContent=`.nav button:hover,.nav button.active,.nav a:hover{background:linear-gradient(90deg,${t.a},${t.a});border-color:${t.a}}.mode-btn.active{background:${t.a};border-color:${t.c}}.primary{background:linear-gradient(135deg,${t.b},${t.b})}.secondary{background:linear-gradient(135deg,${t.a},${t.a})}.round-icon{background:${t.a}}.panel.latest,.panel.market-status,.performance-panel,.chart-panel,.hero{border-color:${t.a}}.hero p,.market-wrap label,.panel-sub,.section-head p{color:${t.c}}.dot{background:${t.b};box-shadow:0 0 13px ${t.b}}.online b,.auto-status,.good,.chart-live{color:${t.b}}.auto-box input{accent-color:${t.a}}`;
    localStorage.setItem(KEY,name);
  }
  function soundEnabled(){return localStorage.getItem(SOUND_KEY)!=='off'}
  let audio;
  function playSignalSound(){
    if(!soundEnabled())return;
    try{
      audio=audio||new (window.AudioContext||window.webkitAudioContext)();
      if(audio.state==='suspended')audio.resume();
      const o=audio.createOscillator(),g=audio.createGain(),now=audio.currentTime;
      o.type='sine';o.frequency.setValueAtTime(880,now);o.frequency.setValueAtTime(1175,now+.09);
      g.gain.setValueAtTime(.0001,now);g.gain.exponentialRampToValueAtTime(.12,now+.015);g.gain.exponentialRampToValueAtTime(.0001,now+.22);
      o.connect(g);g.connect(audio.destination);o.start(now);o.stop(now+.23);
    }catch(_){ }
  }
  function attachSettings(){
    const t=document.getElementById('modal-title'),x=document.getElementById('modal-extra');
    if(!t||!x||t.textContent.trim()!=='Settings'||x.dataset.mmcUiEnhanced==='1')return;
    x.dataset.mmcUiEnhanced='1';
    const theme=localStorage.getItem(KEY)||'blue',sound=soundEnabled();
    x.insertAdjacentHTML('beforeend',`<label class="setting-row">Theme Color <select id="mmc-theme-color" style="background:#0a2440;color:#eaf4ff;border:1px solid #20486e;border-radius:6px;padding:6px 8px"><option value="blue">Blue</option><option value="cyan">Cyan</option><option value="purple">Purple</option><option value="green">Green</option><option value="orange">Orange</option></select></label><label class="setting-row">Signal Sound <input type="checkbox" id="mmc-signal-sound" ${sound?'checked':''}></label>`);
    const sel=document.getElementById('mmc-theme-color');
    if(sel){sel.value=theme;sel.onchange=()=>applyTheme(sel.value)}
    document.getElementById('mmc-signal-sound')?.addEventListener('change',e=>localStorage.setItem(SOUND_KEY,e.target.checked?'on':'off'));
  }
  applyTheme(localStorage.getItem(KEY)||'blue');
  const result=document.getElementById('result-container');
  if(result){
    let last='';
    new MutationObserver(()=>{
      const text=result.textContent.replace(/\s+/g,' ').trim();
      if(text&&text!==last&&/\b(BUY|SELL)\b/.test(text)){last=text;playSignalSound()}
    }).observe(result,{childList:true,subtree:true,characterData:true});
  }
  const modal=document.getElementById('modal');
  if(modal){new MutationObserver(attachSettings).observe(modal,{attributes:true,childList:true,subtree:true});attachSettings()}
})();
