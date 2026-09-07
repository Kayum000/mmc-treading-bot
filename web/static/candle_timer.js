(() => {
  'use strict';

  const pad = (v) => String(v).padStart(2, '0');
  let directionRequestInFlight = false;
  let lastDirectionKey = '';
  let lastDirectionData = null;
  let lastHeroEventKey = '';
  let lastHeroQueueKey = '';
  let chartTimer = null;
  let chartRequestInFlight = false;
  let chartSymbol = '';
  let chartInterval = '1m';
  let lastChartBars = [];
  let chartZoom = 1;
  let chartOffset = 0;
  let chartAnalysis = true;
  let chartDragX = null;

  function renderClock() {
    const el = document.querySelector('[data-bd-clock]');
    if (!el) return;
    const now = new Date();
    const bd = new Date(now.getTime() + 6 * 60 * 60 * 1000);
    el.textContent = `${pad(bd.getUTCHours())}:${pad(bd.getUTCMinutes())}:${pad(bd.getUTCSeconds())}`;
  }

  function renderEntryCountdown() {
    const el = document.querySelector('[data-entry-timer]');
    if (!el) return;
    const at = Date.parse(el.dataset.entryAt || '');
    if (!Number.isFinite(at)) return;
    const seconds = Math.max(0, Math.ceil((at - Date.now()) / 1000));
    const m = Math.floor(seconds / 60), s = seconds % 60;
    const text = seconds > 0 ? `${pad(m)}:${pad(s)}` : '00:00 — ENTRY NOW';
    if (el.textContent !== text) el.textContent = text;
    el.setAttribute('aria-label', seconds > 0 ? `Entry starts in ${m} minutes ${s} seconds` : 'Entry time reached');
  }

  function injectStyles() {
    if (document.getElementById('important-news-styles')) return;
    const style = document.createElement('style');
    style.id = 'important-news-styles';
    style.textContent = `
      #important-news-hero{margin:0 0 8px;padding:10px;border:2px solid #f59e0b;border-radius:11px;background:#fff8dc;box-shadow:0 2px 8px rgba(0,0,0,.06)}
      #important-news-hero .important-news-heading{font-size:19px;font-weight:900;margin-bottom:5px;color:#9a5b00}
      #important-news-hero .important-news-title{font-size:17px;font-weight:900;line-height:1.3;margin:4px 0}
      #important-news-hero .important-news-time{font-size:14px;font-weight:900;line-height:1.3;margin:5px 0;padding:5px 7px;border-radius:8px;background:#fff;border:1px solid #f3c66b}
      #important-news-hero .important-news-count{font-size:14px;font-weight:900;margin:4px 0}
      #important-news-hero .important-news-direction{display:flex;align-items:center;justify-content:center;min-height:0;margin:5px 0;padding:5px;border-radius:9px;font-size:24px;font-weight:1000;letter-spacing:.5px;border:2px solid #cbd5e1;background:#f8fafc}
      #important-news-hero .important-news-direction.up{color:#15803d;border-color:#86efac;background:#f0fdf4}
      #important-news-hero .important-news-direction.down{color:#dc2626;border-color:#fca5a5;background:#fef2f2}
      #important-news-hero .important-news-direction.wait{color:#92400e;border-color:#fcd34d;background:#fffbeb}
      #important-news-hero .important-news-source{font-size:11px;color:#64748b;margin-top:4px}
      #important-news-hero .important-news-queue-label{font-size:12px;font-weight:900;color:#9a5b00;margin:7px 0 4px}
      #important-news-hero .important-news-queue{display:flex;flex-direction:column;gap:4px;max-height:190px;overflow:auto;padding-right:2px}
      #important-news-hero .important-news-queue-item{padding:5px 7px;border:1px solid #f3c66b;border-radius:7px;background:#fff;font-size:12px;line-height:1.25}
      #important-news-hero .important-news-queue-item.nearest{border:2px solid #dc2626;background:#fff7ed}
      #important-news-hero .important-news-queue-item strong{display:block;font-size:11px;margin-bottom:2px}
      #important-news-hero .important-news-queue-item span{display:block;font-size:11px;font-weight:800;margin-top:2px}
      #live-market-chart{margin-top:16px;border:1px solid #cbd5e1;border-radius:12px;background:#0f172a;overflow:hidden;color:#e2e8f0}
      #live-market-chart .chart-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 12px;background:#111827;flex-wrap:wrap}
      #live-market-chart .chart-title{font-size:17px;font-weight:900}
      #live-market-chart .chart-price{font-size:13px;font-weight:900}
      #live-market-chart .chart-controls{display:flex;gap:5px;flex-wrap:wrap;padding:8px 10px;background:#1e293b}
      #live-market-chart .chart-controls button{font-size:12px;padding:6px 9px;border-radius:7px;background:#334155;color:#e2e8f0;border:1px solid #475569;cursor:pointer}
      #live-market-chart .chart-controls button.active{background:#2563eb;border-color:#2563eb;color:#fff}
      #live-market-chart .chart-canvas-wrap{position:relative;height:360px;width:100%;background:#0f172a;touch-action:none;cursor:crosshair}
      #live-market-chart canvas{display:block;width:100%;height:100%}
      #live-market-chart .chart-status{padding:7px 10px;font-size:11px;color:#94a3b8;background:#111827}
      #live-market-chart .chart-analysis{display:flex;gap:8px;flex-wrap:wrap;padding:7px 10px;background:#0b1220;border-top:1px solid #334155;font-size:11px;font-weight:800}
      #live-market-chart .chart-analysis span{padding:4px 7px;border-radius:6px;background:#1e293b}
      @media(max-width:600px){#important-news-hero{padding:9px}#important-news-hero .important-news-heading{font-size:18px}#important-news-hero .important-news-title{font-size:16px}#important-news-hero .important-news-time{font-size:13px}#important-news-hero .important-news-direction{font-size:22px}#live-market-chart .chart-canvas-wrap{height:300px}}
    `;
    document.head.appendChild(style);
  }

  function escapeText(v) {
    return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function eventTime(node) {
    const m = (node?.textContent || '').match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/);
    return m ? m[0] : '';
  }

  function titleOf(node) {
    const strong = node?.querySelector('strong');
    let title = strong ? strong.textContent.trim() : (node?.textContent || '').trim();
    title = title.replace(/^🚨\s*/, '').replace(/^[^—]+—\s*/, '');
    return title || 'Scheduled News';
  }

  function allNewsSources(content) {
    if (!content) return [];
    return Array.from(content.querySelectorAll(':scope > .news-alert, :scope > .news-list li')).filter(node => !node.closest('#important-news-hero')).map(node => ({node, ms: Date.parse(eventTime(node))})).filter(x => Number.isFinite(x.ms) && x.ms >= Date.now() - 60 * 1000).sort((a, b) => a.ms - b.ms);
  }

  function importantSources(content) { return allNewsSources(content).filter(x => x.node.classList.contains('news-impact-high') || x.node.classList.contains('news-impact-medium')); }

  function formatBd(iso) {
    const ms = Date.parse(iso); if (!Number.isFinite(ms)) return '';
    const bd = new Date(ms + 6 * 60 * 60 * 1000);
    return `${bd.getUTCFullYear()}-${pad(bd.getUTCMonth()+1)}-${pad(bd.getUTCDate())} ${pad(bd.getUTCHours())}:${pad(bd.getUTCMinutes())}:${pad(bd.getUTCSeconds())} Bangladesh Time`;
  }

  function countdownText(ms) {
    const seconds = Math.max(0, Math.ceil((ms - Date.now()) / 1000));
    if (seconds <= 0) return 'Event time reached';
    const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
    if (h > 0) return `In ${h}h ${m}m`; return `In ${m}m ${s}s`;
  }

  function directionForSource(source) { if (!source || !lastDirectionData?.event) return null; return eventTime(source) === String(lastDirectionData.event.event_time_utc || '') ? lastDirectionData : null; }

  function ensureHero() {
    let hero = document.getElementById('important-news-hero'); const content = document.getElementById('news-content');
    if (hero || !content) return hero;
    hero = document.createElement('div'); hero.id = 'important-news-hero'; hero.setAttribute('role','status');
    hero.innerHTML = `<div class="important-news-heading">🚨 NEAREST NEWS</div><div class="important-news-title"></div><div class="important-news-time"></div><div class="important-news-time important-news-bd"></div><div class="important-news-count"></div><div class="important-news-direction wait">⏸ WAIT — Direction not confirmed</div><div class="important-news-queue-label">Upcoming News — nearest first:</div><div class="important-news-queue"></div><div class="important-news-source"></div>`;
    content.insertBefore(hero, content.firstChild); return hero;
  }

  function renderHero() {
    const content=document.getElementById('news-content'); if(!content)return; injectStyles(); const items=allNewsSources(content),hero=document.getElementById('important-news-hero');
    if(!items.length){if(hero)hero.remove();lastHeroEventKey='';lastHeroQueueKey='';return;}
    const first=items[0],firstTime=eventTime(first.node),eventKey=`${firstTime}|${titleOf(first.node)}`,queueKey=items.map(x=>`${eventTime(x.node)}|${titleOf(x.node)}|${x.node.className}`).join('||'),box=ensureHero();if(!box)return;
    const important=importantSources(content),directionSource=important[0]?.node||null;
    if(eventKey!==lastHeroEventKey){lastHeroEventKey=eventKey;box.querySelector('.important-news-title').textContent=titleOf(first.node);box.querySelector('.important-news-time').textContent=`🕒 REAL MARKET TIME (UTC): ${firstTime}`;box.querySelector('.important-news-bd').textContent=`🇧🇩 ${formatBd(firstTime)}`;}
    const countNode=box.querySelector('.important-news-count'),countText=`⏱ ${countdownText(first.ms)}`;if(countNode.textContent!==countText)countNode.textContent=countText;
    const directionData=directionForSource(directionSource),direction=String(directionData?.event?.direction||'WAIT').toUpperCase(),directionNode=box.querySelector('.important-news-direction'),directionText=direction==='UP'?'⬆ UP':direction==='DOWN'?'⬇ DOWN':'⏸ WAIT — Direction not confirmed',directionClass=`important-news-direction ${direction.toLowerCase()}`;
    if(directionNode.className!==directionClass)directionNode.className=directionClass;if(directionNode.textContent!==directionText)directionNode.textContent=directionText;
    if(queueKey!==lastHeroQueueKey){lastHeroQueueKey=queueKey;const queue=box.querySelector('.important-news-queue');queue.innerHTML=items.map((item,i)=>`<div class="important-news-queue-item ${i===0?'nearest':''}"><strong>${i===0?'🔴 Nearest':'🕒 Next'}</strong><div>${escapeText(titleOf(item.node))}</div><span>UTC: ${escapeText(eventTime(item.node))} — ${escapeText(countdownText(item.ms))}</span></div>`).join('');box.querySelector('.important-news-source').textContent=`${items.length} upcoming news event(s) • sorted by time.`;}else{const queue=box.querySelector('.important-news-queue');Array.from(queue.children).forEach((node,i)=>{const item=items[i];if(!item)return;const span=node.querySelector('span'),text=`UTC: ${eventTime(item.node)} — ${countdownText(item.ms)}`;if(span&&span.textContent!==text)span.textContent=text;});}
  }

  async function checkAlphaDirection(){const content=document.getElementById('news-content'),important=importantSources(content),source=important[0]?.node;if(!source){lastDirectionKey='';lastDirectionData=null;renderHero();return;}const key=`${eventTime(source)}|${document.getElementById('pair')?.value||''}`;if(directionRequestInFlight||(key===lastDirectionKey&&lastDirectionData?.needed))return;directionRequestInFlight=true;try{const response=await fetch('/news-direction',{method:'GET',cache:'no-store',headers:{'Accept':'application/json'}}),data=await response.json();if(data?.needed){lastDirectionKey=key;lastDirectionData=data;}else{lastDirectionKey='';lastDirectionData=null;}renderHero();}catch(_){renderHero();}finally{directionRequestInFlight=false;}}

  function ensureChart(){
    const panel=document.getElementById('result-container'),pair=document.getElementById('pair')?.value||'';if(!panel||!pair)return null;injectStyles();let chart=document.getElementById('live-market-chart');
    if(!chart){chart=document.createElement('section');chart.id='live-market-chart';chart.innerHTML=`<div class="chart-head"><div class="chart-title">📈 LIVE CHART</div><div class="chart-price" id="chart-price">—</div></div><div class="chart-controls"><button type="button" data-chart-tf="1m" class="active">1M</button><button type="button" data-chart-tf="5m">5M</button><button type="button" data-chart-tf="15m">15M</button><button type="button" data-chart-tf="30m">30M</button><button type="button" data-chart-tf="1h">1H</button><button type="button" data-chart-tool="zoom-out">−</button><button type="button" data-chart-tool="zoom-in">+</button><button type="button" data-chart-tool="reset">RESET</button><button type="button" data-chart-tool="analysis" class="active">ANALYSIS</button></div><div class="chart-canvas-wrap"><canvas id="live-market-canvas"></canvas></div><div class="chart-analysis" id="chart-analysis"><span id="analysis-trend">Trend: —</span><span id="analysis-sma">SMA20: —</span><span id="analysis-ema">EMA20: —</span><span id="analysis-sr">Support/Resistance: —</span></div><div class="chart-status" id="chart-status">Waiting for live market data…</div>`;panel.appendChild(chart);
      chart.querySelectorAll('[data-chart-tf]').forEach(btn=>btn.addEventListener('click',()=>{chartInterval=btn.dataset.chartTf||'1m';chart.querySelectorAll('[data-chart-tf]').forEach(b=>b.classList.toggle('active',b===btn));chartZoom=1;chartOffset=0;loadLiveChart(true);}));
      chart.querySelector('[data-chart-tool="zoom-in"]').addEventListener('click',()=>{chartZoom=Math.min(4,chartZoom*1.25);drawLiveChart();});
      chart.querySelector('[data-chart-tool="zoom-out"]').addEventListener('click',()=>{chartZoom=Math.max(.5,chartZoom/1.25);drawLiveChart();});
      chart.querySelector('[data-chart-tool="reset"]').addEventListener('click',()=>{chartZoom=1;chartOffset=0;drawLiveChart();});
      chart.querySelector('[data-chart-tool="analysis"]').addEventListener('click',e=>{chartAnalysis=!chartAnalysis;e.currentTarget.classList.toggle('active',chartAnalysis);document.getElementById('chart-analysis').style.display=chartAnalysis?'flex':'none';drawLiveChart();});
      const wrap=chart.querySelector('.chart-canvas-wrap');wrap.addEventListener('wheel',e=>{e.preventDefault();chartZoom=Math.max(.5,Math.min(4,chartZoom*(e.deltaY<0?1.15:.87)));drawLiveChart();},{passive:false});wrap.addEventListener('pointerdown',e=>{chartDragX=e.clientX;wrap.setPointerCapture?.(e.pointerId);});wrap.addEventListener('pointermove',e=>{if(chartDragX===null)return;const dx=e.clientX-chartDragX;chartDragX=e.clientX;chartOffset-=dx;drawLiveChart();});wrap.addEventListener('pointerup',()=>{chartDragX=null;});wrap.addEventListener('pointercancel',()=>{chartDragX=null;});window.addEventListener('resize',drawLiveChart,{passive:true});
    }
    return chart;
  }

  function resizeCanvas(canvas){const rect=canvas.getBoundingClientRect(),ratio=Math.max(1,window.devicePixelRatio||1),w=Math.max(320,Math.floor(rect.width*ratio)),h=Math.max(220,Math.floor(rect.height*ratio));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}return{w,h,ratio};}

  function sma(values,n){if(values.length<n)return null;return values.slice(-n).reduce((a,b)=>a+b,0)/n;}
  function ema(values,n){if(values.length<n)return null;let e=values.slice(0,n).reduce((a,b)=>a+b,0)/n,k=2/(n+1);for(let i=n;i<values.length;i++)e=values[i]*k+e*(1-k);return e;}

  function updateAnalysis(){
    const a=document.getElementById('chart-analysis');if(!a||!lastChartBars.length)return;const closes=lastChartBars.map(b=>b.close),last=closes.at(-1),s=sma(closes,20),e=ema(closes,20),window=lastChartBars.slice(-30),support=Math.min(...window.map(b=>b.low)),resistance=Math.max(...window.map(b=>b.high));
    const trend=s==null?'WAIT':last>s?'BULLISH':'BEARISH';document.getElementById('analysis-trend').textContent=`Trend: ${trend}`;document.getElementById('analysis-sma').textContent=`SMA20: ${s==null?'—':s.toFixed(5)}`;document.getElementById('analysis-ema').textContent=`EMA20: ${e==null?'—':e.toFixed(5)}`;document.getElementById('analysis-sr').textContent=`Support/Resistance: ${support.toFixed(5)} / ${resistance.toFixed(5)}`;
  }

  function drawLiveChart(){
    const canvas=document.getElementById('live-market-canvas');if(!canvas||!lastChartBars.length)return;const {w,h,ratio}=resizeCanvas(canvas),ctx=canvas.getContext('2d');ctx.clearRect(0,0,w,h);
    const visible=Math.max(20,Math.min(lastChartBars.length,Math.floor(lastChartBars.length/chartZoom))),start=Math.max(0,Math.min(lastChartBars.length-visible,Math.round(chartOffset))),bars=lastChartBars.slice(start,start+visible);if(!bars.length)return;
    const padX=48*ratio,padTop=14*ratio,padBottom=26*ratio,plotW=w-padX-8*ratio,plotH=h-padTop-padBottom,highs=bars.map(b=>b.high),lows=bars.map(b=>b.low),max=Math.max(...highs),min=Math.min(...lows),span=Math.max(max-min,max*0.00001),y=p=>padTop+(max-p)/span*plotH,step=plotW/Math.max(1,bars.length),bodyW=Math.max(2*ratio,Math.min(12*ratio,step*.62));
    ctx.strokeStyle='#334155';ctx.lineWidth=ratio;for(let i=0;i<5;i++){const gy=padTop+i*plotH/4;ctx.beginPath();ctx.moveTo(padX,gy);ctx.lineTo(w-8*ratio,gy);ctx.stroke();ctx.fillStyle='#94a3b8';ctx.font=`${10*ratio}px Arial`;const pv=max-span*i/4;ctx.fillText(pv.toFixed(Math.max(2,Math.min(5,String(pv).split('.')[1]?.length||2))),3*ratio,gy-2*ratio);}
    bars.forEach((b,i)=>{const x=padX+i*step+step/2,yo=y(b.open),yc=y(b.close),yh=y(b.high),yl=y(b.low),up=b.close>=b.open;ctx.strokeStyle=up?'#22c55e':'#ef4444';ctx.fillStyle=ctx.strokeStyle;ctx.lineWidth=Math.max(1,ratio);ctx.beginPath();ctx.moveTo(x,yh);ctx.lineTo(x,yl);ctx.stroke();const top=Math.min(yo,yc),bh=Math.max(ratio,Math.abs(yc-yo));ctx.fillRect(x-bodyW/2,top,bodyW,bh);});
    if(chartAnalysis){const closes=bars.map(b=>b.close),s20=sma(closes,20),e20=ema(closes,20);if(s20!=null){ctx.strokeStyle='#38bdf8';ctx.lineWidth=2*ratio;ctx.beginPath();bars.forEach((_,i)=>{const local=closes.slice(0,i+1);const v=sma(local,20);if(v==null)return;const x=padX+i*step+step/2;i===0||!Number.isFinite(v)?ctx.moveTo(x,y(v)):ctx.lineTo(x,y(v));});ctx.stroke();}if(e20!=null){ctx.strokeStyle='#fbbf24';ctx.lineWidth=2*ratio;ctx.beginPath();bars.forEach((_,i)=>{const local=closes.slice(0,i+1);const v=ema(local,20);if(v==null)return;const x=padX+i*step+step/2;i===0||!Number.isFinite(v)?ctx.moveTo(x,y(v)):ctx.lineTo(x,y(v));});ctx.stroke();}}
    const last=lastChartBars.at(-1);ctx.fillStyle='#f8fafc';ctx.font=`${11*ratio}px Arial`;ctx.fillText(`LIVE • ${chartSymbol} • ${chartInterval.toUpperCase()} • ZOOM ${chartZoom.toFixed(2)}x`,padX,h-8*ratio);updateAnalysis();
  }

  function timeframeMs(){return ({'1m':60000,'5m':300000,'15m':900000,'30m':1800000,'1h':3600000}[chartInterval]||60000);}
  function updateCurrentCandle(price,ts){
    if(!Number.isFinite(price)||!Number.isFinite(ts)||!lastChartBars.length)return;const tf=timeframeMs(),bucket=Math.floor(ts/tf)*tf,last=lastChartBars.at(-1);
    if(last.time===bucket){last.high=Math.max(last.high,price);last.low=Math.min(last.low,price);last.close=price;}
    else if(bucket>last.time){lastChartBars.push({time:bucket,open:price,high:price,low:price,close:price,isOpen:true});if(lastChartBars.length>160)lastChartBars=lastChartBars.slice(-160);}
    const p=document.getElementById('chart-price');if(p)p.textContent=`${price} • ${new Date(ts).toISOString().replace('T',' ').replace('.000Z',' UTC')}`;drawLiveChart();
  }

  async function pollLiveTick(){
    if(!chartSymbol)return;try{const symbol=encodeURIComponent(chartSymbol.replace('/','').toUpperCase()),response=await fetch(`https://biquote.io/api/${symbol}`,{cache:'no-store',headers:{Accept:'application/json'}});if(!response.ok)throw new Error(`HTTP ${response.status}`);const d=await response.json(),price=Number(d?.mid ?? d?.bid ?? d?.ask),ts=Date.parse(d?.timestamp||d?.time||'')||Date.now();if(Number.isFinite(price))updateCurrentCandle(price,ts);}catch(_){/* keep chart running from last known candle */}
  }

  async function loadLiveChart(force=false){
    const pair=document.getElementById('pair')?.value||'',chart=ensureChart();if(!pair||!chart||chartRequestInFlight)return;if(!force&&pair===chartSymbol&&lastChartBars.length)return;
    chartSymbol=pair;chartRequestInFlight=true;const status=document.getElementById('chart-status');
    try{const symbol=encodeURIComponent(pair.replace('/','').toUpperCase()),interval=encodeURIComponent(chartInterval),response=await fetch(`https://biquote.io/api/${symbol}/ohlc?interval=${interval}&limit=120`,{cache:'no-store',headers:{Accept:'application/json'}});if(!response.ok)throw new Error(`HTTP ${response.status}`);const payload=await response.json(),bars=Array.isArray(payload?.bars)?payload.bars:[];lastChartBars=bars.map(b=>({time:Date.parse(b.openTime),open:+b.open,high:+b.high,low:+b.low,close:+b.close,isOpen:!!b.isOpen})).filter(b=>Number.isFinite(b.time)&&Number.isFinite(b.open)&&Number.isFinite(b.high)&&Number.isFinite(b.low)&&Number.isFinite(b.close)).sort((a,b)=>a.time-b.time);if(!lastChartBars.length)throw new Error('No candles');const latest=lastChartBars.at(-1),price=document.getElementById('chart-price');if(price)price.textContent=`${latest.close} • ${new Date(latest.time).toISOString().replace('T',' ').replace('.000Z',' UTC')}`;if(status)status.textContent=`LIVE • BiQuote • ${chartSymbol} • ${chartInterval.toUpperCase()} • no page refresh • live candle updates`;drawLiveChart();await pollLiveTick();}catch(err){if(status)status.textContent=`Live chart unavailable: ${err.message||'data error'}`;}finally{chartRequestInFlight=false;}
  }

  function syncChartToMarket(){
    const pair=document.getElementById('pair')?.value||'';if(!pair){document.getElementById('live-market-chart')?.remove();chartSymbol='';lastChartBars=[];if(chartTimer)clearInterval(chartTimer);chartTimer=null;return;}
    if(pair!==chartSymbol){lastChartBars=[];chartZoom=1;chartOffset=0;loadLiveChart(true);}if(chartTimer)clearInterval(chartTimer);chartTimer=window.setInterval(pollLiveTick,2000);
  }

  function render(){renderClock();renderEntryCountdown();renderHero();}
  render();window.setInterval(render,1000);window.setInterval(checkAlphaDirection,30000);

  const content=document.getElementById('news-content');if(content&&'MutationObserver'in window){let timer=null;const observer=new MutationObserver(()=>{window.clearTimeout(timer);timer=window.setTimeout(()=>{renderHero();checkAlphaDirection();},80);});observer.observe(content,{childList:true,subtree:true});}

  const pairSelect=document.getElementById('pair');if(pairSelect){pairSelect.addEventListener('change',()=>{chartSymbol='';lastChartBars=[];syncChartToMarket();});syncChartToMarket();}
  if(!document.getElementById('english-ui-script')){const script=document.createElement('script');script.id='english-ui-script';script.src='/static/english_ui.js';script.defer=true;document.head.appendChild(script);}
})();
