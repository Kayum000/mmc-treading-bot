(() => {
  'use strict';

  const HUB = 'https://biquote.io/hubs/tick';
  const CDN = 'https://cdnjs.cloudflare.com/ajax/libs/microsoft-signalr/8.0.0/signalr.min.js';
  const state = { connection: null, symbol: '', interval: '1m', bars: [], loading: false, connected: false, lastTick: 0, raf: 0 };

  const intervalMs = () => ({'1m':60000,'5m':300000,'15m':900000,'30m':1800000,'1h':3600000}[state.interval] || 60000);
  const n = v => Number(v);
  const esc = v => String(v ?? '').replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));

  function injectCss() {
    if (document.getElementById('live-stream-chart-css')) return;
    const s = document.createElement('style'); s.id = 'live-stream-chart-css';
    s.textContent = `
      #live-stream-canvas{position:absolute;inset:0;width:100%;height:100%;z-index:2;pointer-events:none}
      #live-market-chart .chart-canvas-wrap{position:relative;overflow:hidden}
      #live-market-chart .live-stream-badge{display:inline-flex;align-items:center;gap:5px;margin-left:8px;padding:3px 7px;border-radius:999px;background:#172554;color:#93c5fd;font-size:10px;font-weight:900}
      #live-market-chart .live-stream-badge.on{background:#052e16;color:#86efac}
      #live-market-chart .live-stream-badge.off{background:#3f1d1d;color:#fca5a5}
    `; document.head.appendChild(s);
  }

  function loadSignalR() {
    return new Promise((resolve, reject) => {
      if (window.signalR) return resolve(window.signalR);
      const s = document.createElement('script'); s.src = CDN; s.async = true;
      s.onload = () => window.signalR ? resolve(window.signalR) : reject(new Error('SignalR unavailable'));
      s.onerror = () => reject(new Error('SignalR CDN failed'));
      document.head.appendChild(s);
    });
  }

  async function history() {
    if (!state.symbol) return;
    state.loading = true;
    try {
      const r = await fetch(`https://biquote.io/api/${encodeURIComponent(state.symbol)}/ohlc?interval=${state.interval}&limit=160`, {cache:'no-store'});
      const data = await r.json();
      const bars = Array.isArray(data?.bars) ? data.bars : [];
      state.bars = bars.map(b => ({t:Date.parse(b.openTime),o:n(b.open),h:n(b.high),l:n(b.low),c:n(b.close),open:!!b.isOpen})).filter(b => Number.isFinite(b.t) && [b.o,b.h,b.l,b.c].every(Number.isFinite)).slice(-160);
      draw();
    } catch (_) { setStatus('Live stream: history unavailable — waiting for ticks…'); }
    finally { state.loading = false; }
  }

  function bucket(ts) { const m = intervalMs(); return Math.floor(ts / m) * m; }

  function applyTick(tick) {
    if (!tick || String(tick.symbol || '').toUpperCase() !== state.symbol) return;
    const price = n(tick.mid ?? tick.last ?? ((n(tick.bid)+n(tick.ask))/2));
    const ts = Date.parse(tick.timestamp || tick.lastQuoteAt || new Date().toISOString());
    if (!Number.isFinite(price) || !Number.isFinite(ts)) return;
    state.lastTick = ts;
    const bt = bucket(ts);
    let b = state.bars[state.bars.length - 1];
    if (!b || b.t !== bt) {
      const prev = b?.c ?? price;
      b = {t:bt,o:prev,h:price,l:price,c:price,open:true};
      state.bars.push(b);
      if (state.bars.length > 220) state.bars.shift();
    } else {
      b.c = price; b.h = Math.max(b.h, price); b.l = Math.min(b.l, price); b.open = true;
    }
    const priceEl = document.getElementById('chart-price'); if (priceEl) priceEl.textContent = `${state.symbol}  ${price}`;
    setStatus(`LIVE • BiQuote tick stream • ${new Date(ts).toLocaleTimeString('en-GB',{hour12:false})} UTC`);
    draw();
  }

  function setStatus(text) { const el=document.getElementById('chart-status'); if(el) el.textContent=text; const badge=document.querySelector('.live-stream-badge'); if(badge){badge.classList.toggle('on',state.connected);badge.classList.toggle('off',!state.connected);badge.textContent=state.connected?'● LIVE':'○ CONNECTING';} }

  function sma(vals, p){if(vals.length<p)return null;return vals.slice(-p).reduce((a,b)=>a+b,0)/p;}
  function ema(vals,p){if(!vals.length)return null;const k=2/(p+1);let e=vals[0];for(let i=1;i<vals.length;i++)e=vals[i]*k+e*(1-k);return e;}

  function draw() {
    const canvas=document.getElementById('live-stream-canvas'),wrap=canvas?.parentElement;if(!canvas||!wrap)return;
    const r=wrap.getBoundingClientRect(),d=Math.max(1,window.devicePixelRatio||1),w=Math.max(1,Math.floor(r.width*d)),h=Math.max(1,Math.floor(r.height*d));
    if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;canvas.style.width=r.width+'px';canvas.style.height=r.height+'px';}
    const ctx=canvas.getContext('2d');ctx.clearRect(0,0,w,h);
    const bars=state.bars.slice(-Math.min(80,Math.max(25,Math.floor(70*(1+Math.log2(Math.max(.5,Number(window.__chartZoom||1))))))));
    if(!bars.length)return;
    const padL=10*d,padR=62*d,padT=10*d,padB=22*d, cw=w-padL-padR,ch=h-padT-padB;
    const lo=Math.min(...bars.map(b=>b.l)),hi=Math.max(...bars.map(b=>b.h)),span=Math.max(hi-lo,Math.abs(hi)*1e-6,1e-8),min=lo-span*.08,max=hi+span*.08;
    const y=v=>padT+(max-v)/(max-min)*ch, gap=cw/bars.length, bw=Math.max(2*d,Math.min(14*d,gap*.62));
    ctx.strokeStyle='rgba(148,163,184,.12)';ctx.lineWidth=d;ctx.font=`${10*d}px sans-serif`;ctx.fillStyle='#94a3b8';
    for(let i=0;i<=5;i++){const yy=padT+ch*i/5;ctx.beginPath();ctx.moveTo(padL,yy);ctx.lineTo(w-padR,yy);ctx.stroke();const val=max-(max-min)*i/5;ctx.fillText(val.toFixed(Math.max(2,Math.min(6,String(val).split('.')[1]?.length||4))),w-padR+6*d,yy+3*d);}
    bars.forEach((b,i)=>{const x=padL+i*gap+gap/2,up=b.c>=b.o;ctx.strokeStyle=up?'#22c55e':'#ef4444';ctx.fillStyle=up?'#22c55e':'#ef4444';ctx.lineWidth=Math.max(1,d);ctx.beginPath();ctx.moveTo(x,y(b.h));ctx.lineTo(x,y(b.l));ctx.stroke();const top=y(Math.max(b.o,b.c)),bot=y(Math.min(b.o,b.c));ctx.fillRect(x-bw/2,top,bw,Math.max(d,bot-top));});
    const closes=bars.map(b=>b.c),sv=sma(closes,20),ev=ema(closes,20);if(sv!=null){ctx.strokeStyle='#38bdf8';ctx.lineWidth=1.5*d;ctx.beginPath();bars.forEach((b,i)=>{const v=sma(closes.slice(0,i+1),20);if(v==null)return;const x=padL+i*gap+gap/2;i?ctx.lineTo(x,y(v)):ctx.moveTo(x,y(v));});ctx.stroke();}if(ev!=null){ctx.strokeStyle='#f59e0b';ctx.lineWidth=1.2*d;ctx.beginPath();bars.forEach((b,i)=>{const v=ema(closes.slice(0,i+1),20);const x=padL+i*gap+gap/2;i?ctx.lineTo(x,y(v)):ctx.moveTo(x,y(v));});ctx.stroke();}
    const last=bars[bars.length-1],ly=y(last.c);ctx.setLineDash([5*d,4*d]);ctx.strokeStyle='#e2e8f0';ctx.beginPath();ctx.moveTo(padL,ly);ctx.lineTo(w-padR,ly);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#e2e8f0';ctx.fillText(last.c.toString(),w-padR+6*d,ly+3*d);
    const trend=sv!=null&&ev!=null?(last.c>sv&&sv>ev?'BULLISH':last.c<sv&&sv<ev?'BEARISH':'MIXED'):'—';const a=document.getElementById('analysis-trend');if(a)a.textContent=`Trend: ${trend}`;const as=document.getElementById('analysis-sma');if(as)as.textContent=`SMA20: ${sv==null?'—':sv.toFixed(5)}`;const ae=document.getElementById('analysis-ema');if(ae)ae.textContent=`EMA20: ${ev==null?'—':ev.toFixed(5)}`;const ar=document.getElementById('analysis-sr');if(ar)ar.textContent=`Support/Resistance: ${lo.toFixed(5)} / ${hi.toFixed(5)}`;
  }

  function ensureCanvas() {
    const chart=document.getElementById('live-market-chart'),wrap=chart?.querySelector('.chart-canvas-wrap');if(!wrap)return null;
    let c=document.getElementById('live-stream-canvas');if(!c){c=document.createElement('canvas');c.id='live-stream-canvas';wrap.appendChild(c);}
    const badgeHolder=chart.querySelector('.chart-title');if(badgeHolder&&!badgeHolder.querySelector('.live-stream-badge')){const b=document.createElement('span');b.className='live-stream-badge off';b.textContent='○ CONNECTING';badgeHolder.appendChild(b);}
    return c;
  }

  async function connect() {
    if(!state.symbol)return;
    try {
      const signalR=await loadSignalR();
      if(state.connection){try{await state.connection.stop();}catch(_){} state.connection=null;}
      const c=new signalR.HubConnectionBuilder().withUrl(HUB).withAutomaticReconnect([0,1000,3000,5000,10000]).build();
      c.on('ReceiveTick',applyTick);
      c.onreconnecting(()=>{state.connected=false;setStatus('LIVE stream reconnecting…');});
      c.onreconnected(async()=>{state.connected=true;setStatus('LIVE • BiQuote tick stream');try{await c.invoke('Subscribe',[state.symbol]);}catch(_){}});
      c.onclose(()=>{state.connected=false;setStatus('LIVE stream disconnected — retrying…');setTimeout(()=>state.symbol&&connect(),4000);});
      await c.start(); state.connection=c; state.connected=true; await c.invoke('Subscribe',[state.symbol]); setStatus('LIVE • BiQuote tick stream');
    } catch (_) { state.connected=false;setStatus('Live stream unavailable — retrying…');setTimeout(()=>state.symbol&&connect(),5000); }
  }

  async function selectSymbol(symbol) {
    symbol=String(symbol||'').trim().toUpperCase();if(!symbol)return;if(symbol===state.symbol&&state.connection)return;
    if(state.connection){try{await state.connection.invoke('Unsubscribe',[state.symbol]);}catch(_){}try{await state.connection.stop();}catch(_){}state.connection=null;}
    state.symbol=symbol;state.bars=[];state.lastTick=0;ensureCanvas();setStatus(`Loading ${symbol} live chart…`);await history();await connect();
  }

  function watch() {
    injectCss();
    const pair=document.getElementById('pair');
    if(!pair){setTimeout(watch,500);return;}
    const start=()=>{const chart=document.getElementById('live-market-chart');if(!chart){setTimeout(start,500);return;}ensureCanvas();pair.addEventListener('change',()=>selectSymbol(pair.value));chart.querySelectorAll('[data-chart-tf]').forEach(b=>b.addEventListener('click',()=>{state.interval=b.dataset.chartTf||'1m';history();}));selectSymbol(pair.value);window.addEventListener('resize',()=>{cancelAnimationFrame(state.raf);state.raf=requestAnimationFrame(draw);},{passive:true});};
    start();
    const obs=new MutationObserver(()=>{if(document.getElementById('live-market-chart')){ensureCanvas();const sym=pair.value;if(sym&&sym.toUpperCase()!==state.symbol)selectSymbol(sym);}});obs.observe(document.body,{childList:true,subtree:true});
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',watch,{once:true});else watch();
})();
