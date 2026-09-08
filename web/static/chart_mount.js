(() => {
  'use strict';
  function mount() {
    const result = document.getElementById('result-container');
    if (!result || document.getElementById('live-market-chart')) return;
    const chart = document.createElement('section');
    chart.id = 'live-market-chart';
    chart.className = 'chart-compact';
    chart.innerHTML = `
      <div class="chart-title"><span>📈 LIVE MARKET CHART</span><span class="live-stream-badge off">○ CONNECTING</span><button type="button" class="chart-full-view" aria-expanded="false">FULL VIEW</button></div>
      <div class="chart-body">
        <div class="chart-head"><span id="chart-price">Select market</span><span id="chart-status">Waiting…</span></div>
        <div class="chart-controls">
          <button type="button" data-chart-tf="1m">1m</button>
          <button type="button" data-chart-tf="5m">5m</button>
          <button type="button" data-chart-tf="15m">15m</button>
          <button type="button" data-chart-tf="30m">30m</button>
          <button type="button" data-chart-tf="1h">1h</button>
        </div>
        <div class="chart-canvas-wrap"></div>
        <div class="chart-foot">Real-time tick stream • closed candles • UTC</div>
      </div>`;
    const style = document.createElement('style');
    style.id = 'live-market-chart-style';
    style.textContent = `
      #live-market-chart{margin-top:16px;border:1px solid #334155;border-radius:12px;background:#0f172a;color:#e2e8f0;padding:9px 12px;box-shadow:0 4px 18px rgba(15,23,42,.12);overflow:hidden}
      #live-market-chart .chart-title{font-size:15px;font-weight:900;display:flex;align-items:center;gap:7px;min-height:27px}
      #live-market-chart .chart-title>span:first-child{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      #live-market-chart .live-stream-badge{font-size:9px;padding:3px 6px;border-radius:999px;font-weight:900;background:#334155;color:#cbd5e1}
      #live-market-chart .live-stream-badge.on{background:#14532d;color:#bbf7d0}.live-stream-badge.off{background:#3f1d1d;color:#fecaca}
      #live-market-chart .chart-full-view{margin-left:auto;font-size:10px;padding:5px 8px;background:#475569;border:1px solid #64748b;color:#fff;border-radius:6px;font-weight:900;cursor:pointer;white-space:nowrap}
      #live-market-chart.chart-compact .chart-body{display:none}
      #live-market-chart.chart-expanded .chart-body{display:block}
      #live-market-chart .chart-head{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:#cbd5e1;margin:8px 0 7px}
      #live-market-chart #chart-price{font-weight:900;color:#f8fafc}.chart-controls{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:7px}
      #live-market-chart .chart-controls button{font-size:11px;padding:5px 8px;background:#1e293b;border:1px solid #475569;color:#e2e8f0;border-radius:6px}
      #live-market-chart .chart-canvas-wrap{height:330px;min-height:250px;position:relative;overflow:hidden;border:1px solid #1e293b;border-radius:8px;background:#0b1220}
      #live-market-chart .chart-foot{font-size:10px;color:#94a3b8;margin-top:6px}
      @media(max-width:600px){#live-market-chart{margin-top:10px;padding:8px 10px}#live-market-chart .chart-canvas-wrap{height:270px;min-height:220px}}
    `;
    document.head.appendChild(style);

    const toggle = chart.querySelector('.chart-full-view');
    toggle.addEventListener('click', async () => {
      if (chart.classList.contains('chart-compact')) {
        chart.classList.remove('chart-compact');
        chart.classList.add('chart-expanded');
        toggle.textContent = 'COMPACT';
        toggle.setAttribute('aria-expanded', 'true');
        setTimeout(() => window.dispatchEvent(new Event('resize')), 80);
      } else {
        chart.classList.remove('chart-expanded');
        chart.classList.add('chart-compact');
        toggle.textContent = 'FULL VIEW';
        toggle.setAttribute('aria-expanded', 'false');
      }
    });

    result.parentElement.insertBefore(chart, result.nextSibling);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true}); else mount();
})();
