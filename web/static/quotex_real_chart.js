(() => {
  'use strict';
  const S = { canvas:null, poll:null, bars:[], quote:null, asset:'', lastW:0, lastH:0, loading:false };
  const modeEl = () => document.getElementById('mode');
  const pairEl = () => document.getElementById('pair');
  const chartEl = () => document.getElementById('live-market-chart');
  const wrapEl = () => chartEl()?.querySelector('.chart-canvas-wrap');
  const realMode = () => (modeEl()?.value || '').toLowerCase() === 'real';
  const assetForPair = p => String(p || '').replace(/[^A-Za-z0-9]/g, '').toUpperCase();
  const num = v => { const n = Number(v); return Number.isFinite(n) ? n : NaN; };
  const ts = v => { const n = Number(v); if (!Number.isFinite(n)) return 0; return n < 1e12 ? n * 1000 : n; };

  function setLegacyVisible(show) {
    const styleId = 'quotex-real-chart-override';
    let style = document.getElementById(styleId);
    if (!style) { style = document.createElement('style'); style.id = styleId; document.head.appendChild(style); }
    style.textContent = show ? '#live-market-chart canvas#live-stream-canvas{display:none!important}' : '';
  }

  function canvas() {
    const wrap = wrapEl();
    if (!wrap) return null;
    wrap.style.position = 'relative';
    let c = wrap.querySelector('#quotex-real-canvas');
    if (!c) {
      c = document.createElement('canvas');
      c.id = 'quotex-real-canvas';
      c.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;z-index:4;pointer-events:none';
      wrap.appendChild(c);
    }
    S.canvas = c;
    return c;
  }

  function resize(c) {
    const r = c.parentElement.getBoundingClientRect();
    const d = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.floor(r.width * d)), h = Math.max(1, Math.floor(r.height * d));
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; S.lastW = w; S.lastH = h; }
  }

  function draw() {
    if (!realMode()) { setLegacyVisible(false); if (S.canvas) S.canvas.remove(); S.canvas = null; return; }
    setLegacyVisible(true);
    const c = canvas(); if (!c) return;
    resize(c);
    const x = c.getContext('2d'); x.clearRect(0,0,c.width,c.height);
    const bars = S.bars.slice(-90); if (!bars.length) return;
    const d = window.devicePixelRatio || 1;
    const L=42*d,R=8*d,T=10*d,B=20*d,W=Math.max(1,c.width-L-R),H=Math.max(1,c.height-T-B);
    const lo=Math.min(...bars.map(b=>b.l)), hi=Math.max(...bars.map(b=>b.h)), span=Math.max(hi-lo,Math.abs(hi)*1e-6,1e-9);
    const y=v=>T+(hi+span*.08-v)/(span*1.16)*H, gap=W/bars.length, bw=Math.max(2*d,Math.min(12*d,gap*.62));
    x.font=`${9*d}px Arial`; x.fillStyle='#94a3b8'; x.strokeStyle='#334155'; x.lineWidth=1*d;
    for(let i=0;i<4;i++){const yy=T+H*i/3;x.beginPath();x.moveTo(L,yy);x.lineTo(c.width-R,yy);x.stroke();const v=hi+span*.08-(span*1.16)*i/3;x.fillText(v.toFixed(Math.max(2,Math.min(6,Math.floor(-Math.log10(Math.max(v,1e-9))))+2)),4*d,yy+3*d);}
    bars.forEach((b,i)=>{const xx=L+i*gap+gap/2,up=b.c>=b.o;x.strokeStyle=up?'#22c55e':'#ef4444';x.fillStyle=x.strokeStyle;x.beginPath();x.moveTo(xx,y(b.h));x.lineTo(xx,y(b.l));x.stroke();const top=y(Math.max(b.o,b.c)),bot=y(Math.min(b.o,b.c));x.fillRect(xx-bw/2,top,bw,Math.max(d,bot-top));});
    const q=S.quote?.price; if(Number.isFinite(q)){x.strokeStyle='#38bdf8';x.setLineDash([4*d,3*d]);x.beginPath();x.moveTo(L,y(q));x.lineTo(c.width-R,y(q));x.stroke();x.setLineDash([]);x.fillStyle='#e0f2fe';x.fillText(q.toFixed(5),L+4*d,Math.max(10*d,Math.min(c.height-4*d,y(q)-4*d)));}
    const pEl=chartEl()?.querySelector('.chart-price'); if(pEl&&Number.isFinite(q)) pEl.textContent=`Quotex ${q.toFixed(5)}`;
    const title=chartEl()?.querySelector('.chart-title'); if(title) title.textContent=`QUOTEX LIVE — ${S.asset}`;
  }

  async function load() {
    if(!realMode() || S.loading)return;
    const pair=pairEl()?.value||''; const asset=assetForPair(pair); if(!asset)return;
    S.asset=asset; S.loading=true;
    try{
      const r=await fetch(`/quotex/real-market?asset=${encodeURIComponent(asset)}`,{cache:'no-store',credentials:'same-origin'});
      if(!r.ok)return; const d=await r.json();
      if(Array.isArray(d.bars)) S.bars=d.bars.map(b=>({t:ts(b.timestamp),o:num(b.open),h:num(b.high),l:num(b.low),c:num(b.close)})).filter(b=>b.t&&[b.o,b.h,b.l,b.c].every(Number.isFinite)).slice(-180);
      if(d.quote) S.quote={price:num(d.quote.price),timestamp:ts(d.quote.timestamp||d.quote.time)};
      // Expose the same live Real-Market candles to the Performance resolver.
      // The resolver uses the signal candle timestamp to score the completed
      // entry candle, so it must not depend on the chart's private S.bars state.
      window.__mmcChartBars=S.bars.slice();
      window.__mmcChartMarketNow=Date.now();
      draw();
    }catch(_){ draw(); }
    finally{ S.loading=false; }
  }

  function start() {
    clearInterval(S.poll);
    if(!realMode()){setLegacyVisible(false);return;}
    load();
    // The collector already streams fresh market data; 2s polling keeps the UI responsive
    // without creating a request every second or overlapping requests on slower networks.
    S.poll=setInterval(load,2000);
  }
  function watch(){
    const pair=pairEl(); if(!pair){setTimeout(watch,500);return;}
    const chart=chartEl(); if(!chart){setTimeout(watch,500);return;}
    const refresh=()=>{S.bars=[];S.quote=null;start();};
    pair.addEventListener('change',refresh);
    modeEl()?.addEventListener('change',refresh);
    window.addEventListener('mmc-market-changed',refresh,{passive:true});
    window.addEventListener('resize',draw,{passive:true});
    start();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',watch,{once:true});else watch();
})();
