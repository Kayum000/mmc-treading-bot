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
      #live-market-chart .chart-controls button{font-size:12px;padding:6px 9px;border-radius:7px;background:#334155;color:#e2e8f0;border:1px solid #475569}
      #live-market-chart .chart-controls button.active{background:#2563eb;border-color:#2563eb;color:#fff}
      #live-market-chart .chart-canvas-wrap{position:relative;height:360px;width:100%;background:#0f172a}
      #live-market-chart canvas{display:block;width:100%;height:100%}
      #live-market-chart .chart-status{padding:7px 10px;font-size:11px;color:#94a3b8;background:#111827}
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
    return Array.from(content.querySelectorAll(':scope > .news-alert, :scope > .news-list li'))
      .filter(node => !node.closest('#important-news-hero'))
      .map(node => ({node, ms: Date.parse(eventTime(node))}))
      .filter(x => Number.isFinite(x.ms) && x.ms >= Date.now() - 60 * 1000)
      .sort((a, b) => a.ms - b.ms);
  }

  function importantSources(content) {
    return allNewsSources(content).filter(x => x.node.classList.contains('news-impact-high') || x.node.classList.contains('news-impact-medium'));
  }

  function formatBd(iso) {
    const ms = Date.parse(iso);
    if (!Number.isFinite(ms)) return '';
    const bd = new Date(ms + 6 * 60 * 60 * 1000);
    return `${bd.getUTCFullYear()}-${pad(bd.getUTCMonth()+1)}-${pad(bd.getUTCDate())} ${pad(bd.getUTCHours())}:${pad(bd.getUTCMinutes())}:${pad(bd.getUTCSeconds())} Bangladesh Time`;
  }

  function countdownText(ms) {
    const seconds = Math.max(0, Math.ceil((ms - Date.now()) / 1000));
    if (seconds <= 0) return 'Event time reached';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `In ${h}h ${m}m`;
    return `In ${m}m ${s}s`;
  }

  function directionForSource(source) {
    if (!source || !lastDirectionData?.event) return null;
    return eventTime(source) === String(lastDirectionData.event.event_time_utc || '') ? lastDirectionData : null;
  }

  function ensureHero() {
    let hero = document.getElementById('important-news-hero');
    if (hero) return hero;
    const content = document.getElementById('news-content');
    if (!content) return null;
    hero = document.createElement('div');
    hero.id = 'important-news-hero';
    hero.setAttribute('role', 'status');
    hero.innerHTML = `
      <div class="important-news-heading">🚨 NEAREST NEWS</div>
      <div class="important-news-title"></div>
      <div class="important-news-time"></div>
      <div class="important-news-time important-news-bd"></div>
      <div class="important-news-count"></div>
      <div class="important-news-direction wait">⏸ WAIT — Direction not confirmed</div>
      <div class="important-news-queue-label">Upcoming News — nearest first:</div>
      <div class="important-news-queue"></div>
      <div class="important-news-source"></div>
    `;
    content.insertBefore(hero, content.firstChild);
    return hero;
  }

  function renderHero() {
    const content = document.getElementById('news-content');
    if (!content) return;
    injectStyles();
    const items = allNewsSources(content);
    const hero = document.getElementById('important-news-hero');
    if (!items.length) {
      if (hero) hero.remove();
      lastHeroEventKey = '';
      lastHeroQueueKey = '';
      return;
    }

    const first = items[0];
    const firstTime = eventTime(first.node);
    const eventKey = `${firstTime}|${titleOf(first.node)}`;
    const queueKey = items.map(x => `${eventTime(x.node)}|${titleOf(x.node)}|${x.node.className}`).join('||');
    const box = ensureHero();
    if (!box) return;

    const important = importantSources(content);
    const directionSource = important[0]?.node || null;

    if (eventKey !== lastHeroEventKey) {
      lastHeroEventKey = eventKey;
      box.querySelector('.important-news-title').textContent = titleOf(first.node);
      box.querySelector('.important-news-time').textContent = `🕒 REAL MARKET TIME (UTC): ${firstTime}`;
      box.querySelector('.important-news-bd').textContent = `🇧🇩 ${formatBd(firstTime)}`;
    }

    const countNode = box.querySelector('.important-news-count');
    const countText = `⏱ ${countdownText(first.ms)}`;
    if (countNode.textContent !== countText) countNode.textContent = countText;

    const directionData = directionForSource(directionSource);
    const direction = String(directionData?.event?.direction || 'WAIT').toUpperCase();
    const directionNode = box.querySelector('.important-news-direction');
    const directionText = direction === 'UP' ? '⬆ UP' : direction === 'DOWN' ? '⬇ DOWN' : '⏸ WAIT — Direction not confirmed';
    const directionClass = `important-news-direction ${direction.toLowerCase()}`;
    if (directionNode.className !== directionClass) directionNode.className = directionClass;
    if (directionNode.textContent !== directionText) directionNode.textContent = directionText;

    if (queueKey !== lastHeroQueueKey) {
      lastHeroQueueKey = queueKey;
      const queue = box.querySelector('.important-news-queue');
      queue.innerHTML = items.map((item, i) => `<div class="important-news-queue-item ${i===0?'nearest':''}"><strong>${i===0?'🔴 Nearest':'🕒 Next'}</strong><div>${escapeText(titleOf(item.node))}</div><span>UTC: ${escapeText(eventTime(item.node))} — ${escapeText(countdownText(item.ms))}</span></div>`).join('');
      box.querySelector('.important-news-source').textContent = `${items.length} upcoming news event(s) • sorted by time.`;
    } else {
      const queue = box.querySelector('.important-news-queue');
      Array.from(queue.children).forEach((node, i) => {
        const item = items[i];
        if (!item) return;
        const span = node.querySelector('span');
        const text = `UTC: ${eventTime(item.node)} — ${countdownText(item.ms)}`;
        if (span && span.textContent !== text) span.textContent = text;
      });
    }
  }

  async function checkAlphaDirection() {
    const content = document.getElementById('news-content');
    const important = importantSources(content);
    const source = important[0]?.node;
    if (!source) {
      lastDirectionKey = '';
      lastDirectionData = null;
      renderHero();
      return;
    }
    const key = `${eventTime(source)}|${document.getElementById('pair')?.value || ''}`;
    if (directionRequestInFlight || (key === lastDirectionKey && lastDirectionData?.needed)) return;
    directionRequestInFlight = true;
    try {
      const response = await fetch('/news-direction', {method:'GET', cache:'no-store', headers:{'Accept':'application/json'}});
      const data = await response.json();
      if (data?.needed) { lastDirectionKey = key; lastDirectionData = data; }
      else { lastDirectionKey = ''; lastDirectionData = null; }
      renderHero();
    } catch (_) {
      renderHero();
    } finally { directionRequestInFlight = false; }
  }

  function ensureChart() {
    const panel = document.getElementById('result-container');
    const pair = document.getElementById('pair')?.value || '';
    if (!panel || !pair) return null;
    injectStyles();
    let chart = document.getElementById('live-market-chart');
    if (!chart) {
      chart = document.createElement('section');
      chart.id = 'live-market-chart';
      chart.innerHTML = `
        <div class="chart-head"><div class="chart-title">📈 LIVE CHART</div><div class="chart-price" id="chart-price">—</div></div>
        <div class="chart-controls"><button type="button" data-chart-tf="1m" class="active">1M</button><button type="button" data-chart-tf="5m">5M</button><button type="button" data-chart-tf="15m">15M</button><button type="button" data-chart-tf="30m">30M</button><button type="button" data-chart-tf="1h">1H</button></div>
        <div class="chart-canvas-wrap"><canvas id="live-market-canvas"></canvas></div>
        <div class="chart-status" id="chart-status">Waiting for live market data…</div>
      `;
      panel.appendChild(chart);
      chart.querySelectorAll('[data-chart-tf]').forEach(btn => btn.addEventListener('click', () => {
        chartInterval = btn.dataset.chartTf || '1m';
        chart.querySelectorAll('[data-chart-tf]').forEach(b => b.classList.toggle('active', b === btn));
        loadLiveChart(true);
      }));
      window.addEventListener('resize', drawLiveChart, {passive:true});
    }
    return chart;
  }

  function resizeCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.max(1, window.devicePixelRatio || 1);
    const w = Math.max(320, Math.floor(rect.width * ratio));
    const h = Math.max(220, Math.floor(rect.height * ratio));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    return {w, h, ratio};
  }

  let lastChartBars = [];

  function drawLiveChart() {
    const canvas = document.getElementById('live-market-canvas');
    if (!canvas || !lastChartBars.length) return;
    const {w,h,ratio} = resizeCanvas(canvas);
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0,0,w,h);
    const padX = 42 * ratio, padTop = 14 * ratio, padBottom = 24 * ratio;
    const plotW = w - padX - 8 * ratio, plotH = h - padTop - padBottom;
    const highs = lastChartBars.map(b => b.high), lows = lastChartBars.map(b => b.low);
    const max = Math.max(...highs), min = Math.min(...lows), span = Math.max(max-min, max*0.00001);
    const y = p => padTop + (max-p) / span * plotH;
    const step = plotW / Math.max(1,lastChartBars.length);
    const bodyW = Math.max(2*ratio, Math.min(12*ratio, step*0.62));
    ctx.strokeStyle = '#334155'; ctx.lineWidth = 1*ratio;
    for (let i=0;i<5;i++) { const gy=padTop+i*plotH/4; ctx.beginPath(); ctx.moveTo(padX,gy); ctx.lineTo(w-8*ratio,gy); ctx.stroke(); ctx.fillStyle='#94a3b8'; ctx.font=`${10*ratio}px Arial`; const pv=max-(span*i/4); ctx.fillText(pv.toFixed(Math.max(2, Math.min(5, String(pv).split('.')[1]?.length||2))), 3*ratio, gy-2*ratio); }
    lastChartBars.forEach((b,i) => {
      const x=padX+i*step+step/2, yo=y(b.open), yc=y(b.close), yh=y(b.high), yl=y(b.low);
      const up=b.close>=b.open;
      ctx.strokeStyle=up?'#22c55e':'#ef4444'; ctx.fillStyle=ctx.strokeStyle; ctx.lineWidth=Math.max(1,ratio);
      ctx.beginPath();ctx.moveTo(x,yh);ctx.lineTo(x,yl);ctx.stroke();
      const top=Math.min(yo,yc), bh=Math.max(1*ratio,Math.abs(yc-yo));ctx.fillRect(x-bodyW/2,top,bodyW,bh);
    });
    const last=lastChartBars[lastChartBars.length-1];
    ctx.fillStyle='#f8fafc';ctx.font=`${11*ratio}px Arial`;ctx.fillText(`LIVE • ${chartSymbol} • ${chartInterval.toUpperCase()}`,padX, h-7*ratio);
  }

  async function loadLiveChart(force=false) {
    const pair = document.getElementById('pair')?.value || '';
    const chart = ensureChart();
    if (!pair || !chart || chartRequestInFlight) return;
    if (!force && pair === chartSymbol && lastChartBars.length) return;
    chartSymbol = pair;
    chartRequestInFlight = true;
    const status = document.getElementById('chart-status');
    try {
      const symbol = encodeURIComponent(pair.replace('/','').toUpperCase());
      const interval = encodeURIComponent(chartInterval);
      const response = await fetch(`https://biquote.io/api/${symbol}/ohlc?interval=${interval}&limit=120`, {cache:'no-store', headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const bars = Array.isArray(payload?.bars) ? payload.bars : [];
      lastChartBars = bars.map(b => ({time:Date.parse(b.openTime),open:+b.open,high:+b.high,low:+b.low,close:+b.close,isOpen:!!b.isOpen})).filter(b => Number.isFinite(b.time)&&Number.isFinite(b.open)&&Number.isFinite(b.high)&&Number.isFinite(b.low)&&Number.isFinite(b.close)&&!b.isOpen).sort((a,b)=>a.time-b.time);
      if (!lastChartBars.length) throw new Error('No closed candles');
      const latest = lastChartBars[lastChartBars.length-1];
      const price = document.getElementById('chart-price');
      if (price) price.textContent = `${latest.close} • ${new Date(latest.time).toISOString().replace('T',' ').replace('.000Z',' UTC')}`;
      if (status) status.textContent = `LIVE • BiQuote • ${chartSymbol} • ${chartInterval.toUpperCase()} • ${lastChartBars.length} closed candles`;
      drawLiveChart();
    } catch (err) {
      if (status) status.textContent = `Live chart unavailable: ${err.message || 'data error'}`;
    } finally { chartRequestInFlight = false; }
  }

  function syncChartToMarket() {
    const pair = document.getElementById('pair')?.value || '';
    if (!pair) {
      document.getElementById('live-market-chart')?.remove();
      chartSymbol=''; lastChartBars=[];
      return;
    }
    if (pair !== chartSymbol) { lastChartBars=[]; loadLiveChart(true); }
    if (chartTimer) clearInterval(chartTimer);
    chartTimer = window.setInterval(() => loadLiveChart(true), 15000);
  }

  function render() { renderClock(); renderEntryCountdown(); renderHero(); syncChartToMarket(); }
  render();
  window.setInterval(render, 1000);
  window.setInterval(checkAlphaDirection, 30000);

  const content = document.getElementById('news-content');
  if (content && 'MutationObserver' in window) {
    let timer = null;
    const observer = new MutationObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => { renderHero(); checkAlphaDirection(); }, 80);
    });
    observer.observe(content, {childList:true, subtree:true});
  }

  const pairSelect = document.getElementById('pair');
  if (pairSelect) pairSelect.addEventListener('change', () => { chartSymbol=''; lastChartBars=[]; syncChartToMarket(); });

  if (!document.getElementById('english-ui-script')) {
    const script = document.createElement('script');
    script.id = 'english-ui-script';
    script.src = '/static/english_ui.js';
    script.defer = true;
    document.head.appendChild(script);
  }
})();
