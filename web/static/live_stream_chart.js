(() => {
  'use strict';
  const HUB = 'https://biquote.io/hubs/tick';
  const CDN = 'https://cdnjs.cloudflare.com/ajax/libs/microsoft-signalr/8.0.0/signalr.min.js';
  const S = { connection:null, symbol:'', interval:'1m', bars:[], connected:false, connecting:false, retry:0, reconnectTimer:null, clockTimer:null, healthTimer:null, lastTickAt:0, scaleMin:null, scaleMax:null };
  const MS = () => ({'1m':60000,'5m':300000,'15m':900000,'30m':1800000,'1h':3600000}[S.interval] || 60000);
  const num = v => Number(v);
  const sym = v => String(v || '').replace('/','').toUpperCase();
  const tickSym = t => sym(t?.symbol ?? t?.Symbol ?? t?.instrument ?? t?.Instrument);
  const tickPrice = t => {
    for (const v of [t?.mid,t?.Mid,t?.price,t?.Price,t?.last,t?.Last]) { const n=num(v); if(Number.isFinite(n)) return n; }
    const b=num(t?.bid ?? t?.Bid), a=num(t?.ask ?? t?.Ask);
    return Number.isFinite(b)&&Number.isFinite(a) ? (b+a)/2 : NaN;
  };
  const tickTime = t => {
    for (const v of [t?.timestamp,t?.Timestamp,t?.lastQuoteAt,t?.LastQuoteAt,t?.openTime]) {
      if(typeof v === 'number' && Number.isFinite(v)) return v < 1e12 ? v*1000 : v;
      if(typeof v === 'string') { const d=Date.parse(v); if(Number.isFinite(d)) return d; }
    }
    return Date.now();
  };
  const pad = v => String(v).padStart(2,'0');
  const countdown = () => {
    const e=document.getElementById('chart-candle-countdown'); if(!e) return;
    const b=S.bars.at(-1); if(!b){e.textContent='Candle: --:--';return;}
    const sec=Math.max(0,Math.ceil((b.t+MS()-Date.now())/1000));
    e.textContent=`Candle: ${pad(Math.floor(sec/60))}:${pad(sec%60)}`;
  };
  const status = text => {
    const e=document.getElementById('chart-status'); if(e)e.textContent=text;
    const b=document.querySelector('.live-stream-badge');
    if(b){b.className='live-stream-badge '+(S.connected?'on':'off');b.textContent=S.connected?'● LIVE • BiQuote':'○ '+(S.connecting?'CONNECTING':'RETRYING');}
  };
  function loadSignalR(){
    return new Promise((resolve,reject)=>{
      if(window.signalR) return resolve(window.signalR);
      let s=document.querySelector('script[data-bi-quot-signalr]');
      if(s){s.addEventListener('load',()=>window.signalR?resolve(window.signalR):reject(Error('SignalR unavailable')),{once:true});s.addEventListener('error',()=>reject(Error('SignalR CDN failed')),{once:true});return;}
      s=document.createElement('script');s.src=CDN;s.async=false;s.dataset.biQuotSignalr='1';
      s.onload=()=>window.signalR?resolve(window.signalR):reject(Error('SignalR unavailable'));s.onerror=()=>reject(Error('SignalR CDN failed'));document.head.appendChild(s);
    });
  }
  function bucket(t){return Math.floor(t/MS())*MS();}
  function mergeTick(t){
    if(tickSym(t)!==S.symbol)return false;
    const p=tickPrice(t), ts=tickTime(t); if(!Number.isFinite(p))return false;
    const bt=bucket(ts); let b=S.bars.at(-1);
    if(!b || b.t!==bt){b={t:bt,o:b?.c??p,h:p,l:p,c:p};S.bars.push(b);if(S.bars.length>240)S.bars.shift();}
    else{b.c=p;b.h=Math.max(b.h,p);b.l=Math.min(b.l,p);}
    S.lastTickAt=Date.now();
    const pe=document.getElementById('chart-price');if(pe)pe.textContent=`${S.symbol}  ${p}`;
    status('LIVE • BiQuote'); draw(); return true;
  }
  async function history(){
    if(!S.symbol)return;
    try{
      const r=await fetch(`https://biquote.io/api/${encodeURIComponent(S.symbol)}/ohlc?interval=${S.interval}&limit=240`,{cache:'no-store'});
      if(!r.ok)throw Error(`OHLC ${r.status}`); const d=await r.json();
      S.bars=(Array.isArray(d?.bars)?d.bars:[]).map(b=>({t:Date.parse(b.openTime),o:num(b.open),h:num(b.high),l:num(b.low),c:num(b.close)})).filter(b=>Number.isFinite(b.t)&&[b.o,b.h,b.l,b.c].every(Number.isFinite)).slice(-240);
      S.scaleMin=null;S.scaleMax=null;window.__chartBarsLength=S.bars.length;window.__chartOffset=0;draw();countdown();
    }catch(e){status('Waiting for BiQuote live stream…');}
  }
  async function stop(){
    clearTimeout(S.reconnectTimer);clearInterval(S.healthTimer);S.healthTimer=null;
    const c=S.connection;S.connection=null;S.connected=false;S.connecting=false;
    if(c){try{if(S.symbol)await c.invoke('Unsubscribe',[S.symbol]);}catch(e){}try{await c.stop();}catch(e){}}
  }
  function makeConnection(signalR){
    const c=new signalR.HubConnectionBuilder().withUrl(HUB).withAutomaticReconnect([0,1000,3000,5000,10000,15000]).configureLogging(signalR.LogLevel.Error).build();
    c.on('ReceiveTick',mergeTick);
    c.onreconnecting(()=>{S.connected=false;S.connecting=true;status('LIVE stream reconnecting…');});
    c.onreconnected(async()=>{
      try{await c.invoke('Subscribe',[S.symbol]);S.connected=true;S.connecting=false;S.retry=0;S.lastTickAt=Date.now();status('LIVE • BiQuote');}
      catch(e){status('LIVE stream subscribe failed — retrying…');}
    });
    c.onclose(()=>{
      if(c!==S.connection)return;
      S.connected=false;S.connecting=false;status('LIVE stream disconnected — reconnecting…');
      clearTimeout(S.reconnectTimer);S.reconnectTimer=setTimeout(connect,2000);
    });
    return c;
  }
  async function connect(){
    if(!S.symbol || S.connecting)return;
    S.connecting=true;status('Connecting to BiQuote live stream…');
    try{
      const signalR=await loadSignalR();
      const old=S.connection;S.connection=null;if(old){try{await old.stop();}catch(e){}}
      const c=makeConnection(signalR);S.connection=c;await c.start();
      await c.invoke('Subscribe',[S.symbol]);S.connected=true;S.connecting=false;S.retry=0;S.lastTickAt=Date.now();status('LIVE • BiQuote');
      clearInterval(S.healthTimer);
      S.healthTimer=setInterval(()=>{
        if(S.connection!==c || !S.connected)return;
        if(S.lastTickAt && Date.now()-S.lastTickAt>15000){
          status('LIVE stream stale — reconnecting…');
          try{c.stop();}catch(e){}
        }
      },5000);
    }catch(e){
      S.connected=false;S.connecting=false;S.retry++;status('BiQuote live stream unavailable — retrying…');
      clearTimeout(S.reconnectTimer);S.reconnectTimer=setTimeout(connect,Math.min(15000,2000+S.retry*1000));
    }
  }
  function canvas(){
    const chart=document.getElementById('live-market-chart'),wrap=chart?.querySelector('.chart-canvas-wrap');if(!wrap)return null;
    let c=document.getElementById('live-stream-canvas');
    if(!c){c=document.createElement('canvas');c.id='live-stream-canvas';c.style.cssText='position:absolute;inset:0;width:100%;height:100%;z-index:2;pointer-events:none';wrap.appendChild(c);}
    if(!document.querySelector('.live-stream-badge')){const h=chart.querySelector('.chart-title');if(h){const b=document.createElement('span');b.className='live-stream-badge off';b.textContent='○ CONNECTING';h.appendChild(b);}}
    if(!document.getElementById('chart-candle-countdown')){const h=chart.querySelector('.chart-head');if(h){const e=document.createElement('span');e.id='chart-candle-countdown';e.style.cssText='font-size:12px;font-weight:900;margin-left:6px';e.textContent='Candle: --:--';h.appendChild(e);}}
    return c;
  }
  function draw(){
    const c=canvas();if(!c)return;const r=c.parentElement.getBoundingClientRect(),d=Math.max(1,devicePixelRatio||1),w=Math.max(1,r.width),h=Math.max(1,r.height);
    if(c.width!==Math.floor(w*d)||c.height!==Math.floor(h*d)){c.width=Math.floor(w*d);c.height=Math.floor(h*d);}
    const x=c.getContext('2d');x.clearRect(0,0,c.width,c.height);window.__chartBarsLength=S.bars.length;
    const zoom=Math.max(.5,Math.min(4,Number(window.__chartZoom||1))),visible=Math.max(15,Math.min(120,Math.round(90/zoom))),maxOff=Math.max(0,S.bars.length-visible),off=Math.max(0,Math.min(maxOff,Math.round(window.__chartOffset||0))),end=Math.max(15,S.bars.length-off),start=Math.max(0,end-visible),bs=S.bars.slice(start,end);if(!bs.length)return;
    const rawLo=Math.min(...bs.map(b=>b.l)),rawHi=Math.max(...bs.map(b=>b.h)),span=Math.max(rawHi-rawLo,Math.abs(rawHi)*1e-6,1e-8),targetMin=rawLo-span*.10,targetMax=rawHi+span*.10;
    if(S.scaleMin===null||S.scaleMax===null){S.scaleMin=targetMin;S.scaleMax=targetMax;}else{const blend=.08;S.scaleMin+=(targetMin-S.scaleMin)*blend;S.scaleMax+=(targetMax-S.scaleMax)*blend;}
    const min=S.scaleMin,max=S.scaleMax,T=10*d,B=24*d,L=10*d,R=66*d,W=Math.max(1,c.width-L-R),H=Math.max(1,c.height-T-B),y=v=>T+(max-v)/(max-min)*H;
    x.font=`${10*d}px sans-serif`;x.fillStyle='#94a3b8';x.strokeStyle='rgba(148,163,184,.12)';
    for(let i=0;i<=5;i++){const yy=T+H*i/5;x.beginPath();x.moveTo(L,yy);x.lineTo(c.width-R,yy);x.stroke();x.fillText((max-(max-min)*i/5).toFixed(5),c.width-R+6*d,yy+3*d);}
    const gap=W/bs.length,bw=Math.max(2*d,Math.min(14*d,gap*.62));
    bs.forEach((b,i)=>{const xx=L+i*gap+gap/2,up=b.c>=b.o;x.strokeStyle=up?'#22c55e':'#ef4444';x.fillStyle=up?'#22c55e':'#ef4444';x.beginPath();x.moveTo(xx,y(b.h));x.lineTo(xx,y(b.l));x.stroke();const top=y(Math.max(b.o,b.c)),bot=y(Math.min(b.o,b.c));x.fillRect(xx-bw/2,top,bw,Math.max(d,bot-top));});
    const last=bs.at(-1);x.setLineDash([5*d,4*d]);x.strokeStyle='#e2e8f0';x.beginPath();x.moveTo(L,y(last.c));x.lineTo(c.width-R,y(last.c));x.stroke();x.setLineDash([]);x.fillStyle='#e2e8f0';x.fillText(String(last.c),c.width-R+6*d,y(last.c)+3*d);window.__liveChartRedraw=draw;countdown();
  }
  async function select(v){
    const s=sym(v);if(!s)return;if(s===S.symbol&&S.connection)return;await stop();S.symbol=s;S.bars=[];S.retry=0;S.lastTickAt=0;S.scaleMin=null;S.scaleMax=null;window.__chartZoom=1;window.__chartOffset=0;canvas();status(`Loading ${s} live chart…`);await history();connect();
  }
  function watch(){
    const pair=document.getElementById('pair');if(!pair){setTimeout(watch,500);return;}
    const start=()=>{if(!document.getElementById('live-market-chart')){setTimeout(start,500);return;}canvas();pair.onchange=()=>select(pair.value);
      document.querySelectorAll('#live-market-chart [data-chart-tf]').forEach(b=>{if(!b.dataset.liveBound){b.dataset.liveBound='1';b.addEventListener('click',async()=>{S.interval=b.dataset.chartTf||'1m';S.scaleMin=null;S.scaleMax=null;await history();});}});
      select(pair.value);window.addEventListener('resize',draw,{passive:true});clearInterval(S.clockTimer);S.clockTimer=setInterval(countdown,250);
    };
    start();
    new MutationObserver(()=>{if(document.getElementById('live-market-chart')){canvas();const s=sym(pair.value);if(s&&s!==S.symbol)select(s);}}).observe(document.body,{childList:true,subtree:true});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',watch,{once:true});else watch();
})();
