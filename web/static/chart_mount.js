(() => {
  'use strict';

  function mount() {
    const dashboard = document.querySelector('.dashboard');
    const anchor = document.getElementById('result-container');
    if (!anchor || !dashboard) return;

    document.querySelectorAll('#live-market-chart').forEach((node, i) => { if (i > 0) node.remove(); });

    let chart = document.getElementById('live-market-chart');
    if (!chart) {
      chart = document.createElement('section');
      chart.id = 'live-market-chart';
      chart.className = 'chart-clean';
      chart.innerHTML = '<div class="chart-bar"><span class="chart-title">LIVE CHART</span><span class="chart-price">—</span><button type="button" id="chart-full-view">FULL VIEW</button></div><div class="chart-canvas-wrap"></div>';
    }

    const resetLegacyChart = () => {
      const legacyCanvas = chart.querySelector('#live-market-canvas');
      const legacyControls = chart.querySelector('.chart-controls');
      const legacyAnalysis = chart.querySelector('.chart-analysis');
      const legacyHead = chart.querySelector('.chart-head');
      if (!legacyCanvas && !legacyControls && !legacyAnalysis && !legacyHead) return;
      const currentPrice = chart.querySelector('.chart-price')?.textContent || '—';
      chart.innerHTML = `<div class="chart-bar"><span class="chart-title">LIVE CHART</span><span class="chart-price">${currentPrice}</span><button type="button" id="chart-full-view">FULL VIEW</button></div><div class="chart-canvas-wrap"></div>`;
    };

    function normalizeChart() {
      resetLegacyChart();
      chart.querySelector('.chart-controls')?.remove();
      chart.querySelector('.chart-analysis')?.remove();
      let bar = chart.querySelector('.chart-bar');
      if (!bar) { bar = document.createElement('div'); bar.className = 'chart-bar'; chart.prepend(bar); }
      let title = chart.querySelector('.chart-title');
      if (!title) { title = document.createElement('span'); title.className = 'chart-title'; title.textContent = 'LIVE CHART'; bar.prepend(title); }
      let price = chart.querySelector('.chart-price');
      if (!price) { price = document.createElement('span'); price.className = 'chart-price'; price.textContent = '—'; bar.appendChild(price); }
      let full = bar.querySelector('#chart-full-view');
      if (!full) { full = document.createElement('button'); full.type = 'button'; full.id = 'chart-full-view'; full.textContent = 'FULL VIEW'; bar.appendChild(full); }
      if (full.dataset.bound !== '1') {
        full.dataset.bound = '1';
        full.onclick = (e) => {
          e.preventDefault(); e.stopPropagation();
          const expanded = chart.classList.toggle('chart-expanded');
          full.textContent = expanded ? 'EXIT FULL VIEW' : 'FULL VIEW';
          setTimeout(() => window.dispatchEvent(new Event('resize')), 80);
        };
      }
      if (chart.dataset.doubleClickBound !== '1') {
        chart.dataset.doubleClickBound = '1';
        chart.addEventListener('dblclick', (e) => {
          if (e.target.closest('#chart-full-view')) return;
          const expanded = chart.classList.toggle('chart-expanded');
          full.textContent = expanded ? 'EXIT FULL VIEW' : 'FULL VIEW';
          setTimeout(() => window.dispatchEvent(new Event('resize')), 80);
        });
      }
    }

    normalizeChart();
    if (chart.parentElement !== dashboard || chart.previousElementSibling !== anchor) {
      dashboard.insertBefore(chart, document.getElementById('news-panel'));
    }

    let style = document.getElementById('live-market-chart-style');
    if (!style) { style = document.createElement('style'); style.id = 'live-market-chart-style'; document.head.appendChild(style); }
    style.textContent = `
      .dashboard{grid-template-columns:minmax(420px,1.25fr) minmax(320px,.9fr)!important;grid-auto-flow:row;align-items:start;}
      #result-container{grid-column:1;grid-row:1;}
      #live-market-chart{grid-column:1;grid-row:2;display:flex;flex-direction:column;margin:0;border:1px solid #334155;border-radius:10px;background:#0b1220;padding:0;overflow:hidden;width:100%;height:360px;min-width:0;min-height:220px;max-width:100%;max-height:80vh;box-sizing:border-box;position:relative;}
      #news-panel{grid-column:2!important;grid-row:1 / span 2!important;align-self:stretch;max-height:calc(100vh - 110px);}
      #live-market-chart.chart-expanded{position:fixed;inset:10px;z-index:99999;width:auto!important;height:auto!important;max-width:none;max-height:none;border-radius:12px;box-shadow:0 12px 40px rgba(0,0,0,.45);}
      #live-market-chart .chart-bar{height:38px;min-height:38px;display:flex;align-items:center;gap:10px;padding:0 8px;background:#111827;color:#e5e7eb;font-size:12px;font-weight:900;letter-spacing:.25px;box-sizing:border-box;}
      #live-market-chart .chart-bar .chart-title{display:block;white-space:nowrap;margin:0;color:#f8fafc;font-size:13px;}
      #live-market-chart .chart-bar .chart-price{margin-left:auto;color:#cbd5e1;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
      #live-market-chart .chart-bar #chart-full-view{display:block;flex:0 0 auto;font-size:11px;line-height:1;padding:7px 9px;border-radius:7px;background:#2563eb;color:#fff;border:0;font-weight:900;cursor:pointer;touch-action:manipulation;}
      #live-market-chart .chart-canvas-wrap{position:relative;flex:1;min-height:0;width:100%;overflow:hidden;border-radius:0 0 7px 7px;background:#0b1220;touch-action:none;cursor:grab;}
      #live-market-chart .chart-canvas-wrap:active{cursor:grabbing;}
      #live-market-chart canvas{display:block;width:100%;height:100%;}
      @media(max-width:900px){.dashboard{grid-template-columns:1fr!important;}#result-container,#live-market-chart,#news-panel{grid-column:1!important;grid-row:auto!important;}#result-container{order:1}#live-market-chart{order:2;height:320px}#news-panel{order:3;max-height:none!important;}}
      @media(max-width:600px){#live-market-chart{height:300px;min-height:220px}#live-market-chart.chart-expanded{inset:0;border-radius:0}.news-box{max-height:500px!important}}
    `;

    window.addEventListener('resize', normalizeChart, {passive:true});
    setTimeout(normalizeChart, 100);
    setTimeout(normalizeChart, 500);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true}); else mount();
})();
