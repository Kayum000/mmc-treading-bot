(() => {
  'use strict';
  const HUB='https://biquote.io/hubs/tick';
  const CDN='https://cdnjs.cloudflare.com/ajax/libs/microsoft-signalr/8.0.29/signalr.min.js';
  const S={c:null,symbol:'',interval:'1m',bars:[],timer:null,poll:null,clock:null,scaleMin:null,scaleMax:null};
  const MS=()=>({'1m':60000,'5m':300000,'15m':900000,'30m':1800000,'1h':3600000}[S.interval]||60000);
  const sym=v=>String(v||'').replace('/','').toUpperCase(), num=v=>Number(v);
  const price=t=>{for(const v of[t?.mid,t?.Mid,t?.price,t?.Price,t?.last,t?.Last]){const n=num(v);if(Number.isFinite(n))return n;}const b=num(t?.bid??t?.Bid),a=num(t?.ask??t?.Ask);return Number.isFinite(b)&&Number.isFinite(a)?(b+a)/2:NaN;};
  const ts=t=>{const v=t?.timestamp??t?.Timestamp??t?.lastQuoteAt??t?.LastQuoteAt;const d=typeof v==='number'?new Date(v<1e12?v*1000:v):new Date(v);return Number.isFinite(d.getTime())?d.getTime():Date.now();};
  const fmtUTC=t=>new Date(t).toISOString().slice(0,19).replace('T',' ')+' UTC';
  const pad=n=>String(Math.max(0,n)).padStart(2,'0');
  function ensureBar(chart){
    if(!chart)return null;
    let bar=chart.querySelector('.chart-bar');
    if(!bar){bar=document.createElement('div');bar.className='chart-bar';chart.insertBefore(bar,chart.firstChild);}
    let title=bar.querySelector('.chart-title');
    if(!title){title=document.createElement('span');title.className='chart-title';title.textContent='LIVE CHART';bar.prepend(title);}
    let time=bar.querySelector('.chart-candle-time');
    if(!time){time=document.createElement('span');time.className='chart-candle-time';time.textContent='—';bar.appendChild(time);}
    let countdown=bar.querySelector('.chart-candle-countdown');
    if(!countdown){countdown=document.createElement('span');countdown.className='chart-candle-countdown';countdown.textContent='CLOSE IN —';bar.appendChild(countdown);}
    let live=bar.querySelector('.chart-live-price');
    if(!live){live=document.createElement('span');live.className='chart-live-price';live.textContent='LIVE PRICE —';bar.appendChild(live);}
    let full=bar.querySelector('#chart-full-view');
    if(!full){full=document.createElement('button');full.type='button';full.id='chart-full-view';full.textContent='FULL VIEW';bar.appendChild(full);}
    return bar;
  }
  function updateLiveInfo(){
    const chart=document.querySelector('#live-market-chart');
    const bar=ensureBar(chart); if(!bar)return;
    const b=S.bars.at(-1), now=Date.now(), ms=MS();
    const p=b?.c;
    const pe=bar.querySelector('.chart-live-price'); if(pe)pe.textContent=Number.isFinite(p)?`LIVE PRICE ${p.toFixed(5)}`:'LIVE PRICE —';
    const te=bar.querySelector('.chart-candle-time'); if(te)te.textContent=b?.t?`CANDLE ${fmtUTC(b.t)}`:'CANDLE —';
    const remain=b?.t?Math.max(0,b.t+ms-now):0;
    const ce=bar.querySelector('.chart-candle-countdown'); if(ce)ce.textContent=b?.t?`CLOSE IN ${pad(Math.floor(remain/60000))}:${pad(Math.floor(remain/1000)%60)}`:'CLOSE IN —';
  }
  function canvas(){const chart=document.getElementById('live-market-chart'),wrap=chart?.querySelector('.chart-canvas-wrap');if(!wrap)return null;ensureBar(chart);let c=wrap.querySelector('canvas#live-stream-canvas');if(!c){c=document.createElement('canvas');c.id='live-stream-canvas';c.style.cssText='position:absolute;inset:0;width:100%;height:100%;z-index:2;cursor:grab;touch-action:none';wrap.appendChild(c);bindDrag(c,wrap);}return c;}
  function draw(){const c=canvas();if(!c)return;const r=c.parentElement.getBoundingClientRect(),d=devicePixelRatio||1,w=Math.max(1,r.width),h=Math.max(1,r.height);c.width=Math.floor(w*d);c.height=Math.floor(h*d);const x=c.getContext('2d');x.clearRect(0,0,c.width,c.height);const zoom=Math.max(.5,Math.min(4,Number(window.__chartZoom||1))),visible=Math.max(15,Math.min(120,Math.round(90/zoom))),maxOff=Math.max(0,S.bars.length-visible),off=Math.max(0,Math.min(maxOff,Math.round(window.__chartOffset||0))),end=Math.max(15,S.bars.length-off),bs=S.bars.slice(Math.max(0,end-visible),end);if(!bs.length){updateLiveInfo();return;}const lo=Math.min(...bs.map(b=>b.l)),hi=Math.max(...bs.map(b=>b.h)),sp=Math.max(hi-lo,Math.abs(hi)*1e-6,1e-8),tmin=lo-sp*.1,tmax=hi+sp*.1;if(S.scaleMin==null){S.scaleMin=tmin;S.scaleMax=tmax;}else{S.scaleMin+=(tmin-S.scaleMin)*.08;S.scaleMax+=(tmax-S.scaleMax)*.08;}const T=10*d,B=10*d,L=10*d,R=10*d,W=Math.max(1,c.width-L-R),H=Math.max(1,c.height-T-B),y=v=>T+(S.scaleMax-v)/(S.scaleMax-S.scaleMin)*H,gap=W/bs.length,bw=Math.max(2*d,Math.min(14*d,gap*.62));bs.forEach((b,i)=>{const xx=L+i*gap+gap/2,up=b.c>=b.o;x.strokeStyle=up?'#22c55e':'#ef4444';x.fillStyle=x.strokeStyle;x.beginPath();x.moveTo(xx,y(b.h));x.lineTo(xx,y(b.l));x.stroke();const top=y(Math.max(b.o,b.c)),bot=y(Math.min(b.o,b.c));x.fillRect(xx-bw/2,top,bw,Math.max(d,bot-top));});window.__liveChartRedraw=draw;updateLiveInfo();}
  function bindDrag(c,wrap){let active=false,startX=0,startOffset=0;c.addEventListener('pointerdown',e=>{if(e.button!==undefined&&e.button!==0)return;active=true;startX=e.clientX;startOffset=Number(window.__chartOffset||0);c.setPointerCapture?.(e.pointerId);c.style.cursor='grabbing';});c.addEventListener('pointermove',e=>{if(!active)return;const zoom=Math.max(.5,Math.min(4,Number(window.__chartZoom||1))),visible=Math.max(15,Math.min(120,Math.round(90/zoom))),maxOff=Math.max(0,S.bars.length-visible),gap=Math.max(1,wrap.getBoundingClientRect().width/visible),delta=Math.round((e.clientX-startX)/gap);window.__chartOffset=Math.max(0,Math.min(maxOff,startOffset-delta));draw();});const end=e=>{if(!active)return;active=false;c.style.cursor='grab';try{c.releasePointerCapture?.(e.pointerId);}catch(_){}};c.addEventListener('pointerup',end);c.addEventListener('pointercancel',end);}
  async function history(){try{const r=await fetch(`https://biquote.io/api/${S.symbol}/ohlc?interval=${S.interval}&limit=240`,{cache:'no-store'});if(!r.ok)throw Error(`HTTP ${r.status}`);const d=await r.json();S.bars=(d.bars||[]).map(b=>({t:Date.parse(b.openTime),o:num(b.open),h:num(b.high),l:num(b.low),c:num(b.close)})).filter(b=>Number.isFinite(b.t)&&[b.o,b.h,b.l,b.c].every(Number.isFinite)).slice(-240);S.scaleMin=S.scaleMax=null;window.__chartOffset=0;draw();}catch(e){console.warn('BiQuote history',e);}}
  async function latest(){if(!S.symbol)return;try{const r=await fetch(`https://biquote.io/api/${S.symbol}?allowStale=false`,{cache:'no-store'});if(!r.ok)throw Error(`HTTP ${r.status}`);const t=await r.json(),p=price(t);if(!Number.isFinite(p))throw Error('No price');const bt=Math.floor(ts(t)/MS())*MS();let b=S.bars.at(-1);if(!b||b.t!==bt){b={t:bt,o:p,h:p,l:p,c:p};S.bars.push(b);if(S.bars.length>240)S.bars.shift();}else{b.c=p;b.h=Math.max(b.h,p);b.l=Math.min(b.l,p);}draw();}catch(e){console.warn('BiQuote latest',e);}}
  function startFallback(){clearInterval(S.poll);S.poll=setInterval(latest,2000);latest();}
  function stopFallback(){clearInterval(S.poll);S.poll=null;}
  function loadClient(){return new Promise((ok,no)=>{if(window.signalR)return ok();const s=document.createElement('script');s.src=CDN;s.onload=()=>window.signalR?ok():no(Error('SignalR global missing'));s.onerror=()=>no(Error('SignalR client failed to load'));document.head.appendChild(s);});}
  async function stop(){clearTimeout(S.timer);S.timer=null;stopFallback();if(S.c){try{await S.c.stop();}catch(e){}S.c=null;}}
  async function connect(){if(!S.symbol)return;await stop();try{await loadClient();const c=new signalR.HubConnectionBuilder().withUrl(HUB,{withCredentials:false}).withAutomaticReconnect([0,1000,3000,5000,10000]).build();S.c=c;c.on('ReceiveTick',t=>{if(sym(t?.symbol)!==S.symbol)return;const p=price(t);if(!Number.isFinite(p))return;const bt=Math.floor(ts(t)/MS())*MS();let b=S.bars.at(-1);if(!b||b.t!==bt){b={t:bt,o:b?.c??p,h:p,l:p,c:p};S.bars.push(b);if(S.bars.length>240)S.bars.shift();}else{b.c=p;b.h=Math.max(b.h,p);b.l=Math.min(b.l,p);}draw();});c.onreconnected(async()=>{stopFallback();try{await c.invoke('Subscribe',[S.symbol]);}catch(e){console.warn('BiQuote subscribe',e);}});c.onclose(()=>{S.c=null;startFallback();clearTimeout(S.timer);S.timer=setTimeout(connect,15000);});await c.start();await c.invoke('Subscribe',[S.symbol]);stopFallback();}catch(e){console.error('BiQuote stream',e);S.c=null;startFallback();clearTimeout(S.timer);S.timer=setTimeout(connect,15000);}}
  async function select(v){const s=sym(v);if(!s)return;S.symbol=s;S.bars=[];S.scaleMin=S.scaleMax=null;window.__chartZoom=1;window.__chartOffset=0;ensureBar(document.getElementById('live-market-chart'));canvas();await history();await connect();}
  function watch(){const pair=document.getElementById('pair');if(!pair){setTimeout(watch,500);return;}const start=()=>{const chart=document.getElementById('live-market-chart');if(!chart){setTimeout(start,500);return;}ensureBar(chart);canvas();pair.onchange=()=>select(pair.value);select(pair.value);window.addEventListener('resize',draw,{passive:true});clearInterval(S.clock);S.clock=setInterval(updateLiveInfo,250);};start();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',watch,{once:true});else watch();
})();