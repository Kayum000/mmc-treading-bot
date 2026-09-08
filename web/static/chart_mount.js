(() => {
  'use strict';

  function mount() {
    const findAuto = () => document.getElementById('auto-signal')?.closest('.auto-row');
    const findResult = () => document.getElementById('result-container');
    let anchor = findAuto() || findResult();
    if (!anchor || !anchor.parentElement) return;

    function resetLegacyChart(chart) {
      // Older candle_timer builds can create a second canvas/chart first.
      // Keep exactly one chart surface and let live_stream_chart.js own the canvas.
      const legacyCanvas = chart.querySelector('#live-market-canvas');
      const legacyControls = chart.querySelector('.chart-controls');
      const legacyAnalysis = chart.querySelector('.chart-analysis');
      const legacyHead = chart.querySelector('.chart-head');
      if (!legacyCanvas && !legacyControls && !legacyAnalysis && !legacyHead) return;

      const currentPrice = chart.querySelector('.chart-price')?.textContent || '—';
      chart.innerHTML = `<div class="chart-bar"><span class="chart-title">LIVE CHART</span><span class="chart-price">${currentPrice}</span><button type="button" id="chart-full-view">FULL VIEW</button></div><div class="chart-canvas-wrap"></div>`;
    }

    document.querySelectorAll('#live-market-chart').forEach((node, i) => { if (i > 0) node.remove(); });
    let row = document.getElementById('auto-chart-row');
    if (!row) {
      row = document.createElement('div');
      row.id = 'auto-chart-row';
      row.className = 'auto-chart-row';
      anchor.parentElement.insertBefore(row, anchor);
    }

    function normalizeChart(chart) {
      if (!chart) return;
      resetLegacyChart(chart);
      chart.querySelector('.chart-controls')?.remove();
      chart.querySelector('.chart-analysis')?.remove();

      let bar = chart.querySelector('.chart-bar');
      if (!bar) {
        bar = document.createElement('div');
        bar.className = 'chart-bar';
        chart.insertBefore(bar, chart.firstChild);
      }

      const title = chart.querySelector('.chart-title');
      const price = chart.querySelector('.chart-price');
      let full = bar.querySelector('#chart-full-view');
      if (!full) {
        full = document.createElement('button');
        full.type = 'button';
        full.id = 'chart-full-view';
        full.textContent = 'FULL VIEW';
        bar.appendChild(full);
      }
      if (title && title.parentElement !== bar) bar.insertBefore(title, bar.firstChild);
      if (price && price.parentElement !== bar) bar.appendChild(price);

      if (full.dataset.bound !== '1') {
        full.dataset.bound = '1';
        full.onclick = (e) => {
          e.preventDefault();
          e.stopPropagation();
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

    function ensureLayout() {
      const current = findAuto() || findResult();
      if (!current || !current.parentElement) return;
      if (current.parentElement !== row) row.appendChild(current);

      let chart = document.getElementById('live-market-chart');
      if (!chart) {
        chart = document.createElement('section');
        chart.id = 'live-market-chart';
        chart.className = 'chart-clean';
        chart.innerHTML = '<div class="chart-bar"><span class="chart-title">LIVE CHART</span><span class="chart-price">—</span><button type="button" id="chart-full-view">FULL VIEW</button></div><div class="chart-canvas-wrap"></div>';
      }
      if (chart.parentElement !== row) row.appendChild(chart);
      normalizeChart(chart);
    }

    let style = document.getElementById('live-market-chart-style');
    if (!style) {
      style = document.createElement('style');
      style.id = 'live-market-chart-style';
      document.head.appendChild(style);
    }
    style.textContent = `
      #auto-chart-row{display:flex;flex-direction:row;align-items:flex-start;gap:9px;width:100%;margin:0 0 10px 0;box-sizing:border-box;flex-wrap:nowrap;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;}
      #auto-chart-row .auto-row{display:inline-flex;flex:0 0 auto;align-items:center;gap:9px;margin:0;white-space:nowrap;}
      #live-market-chart{display:flex;flex:1 1 700px;flex-direction:column;margin:0;border:1px solid #334155;border-radius:10px;background:#0b1220;padding:0;overflow:hidden;width:100%;height:360px;min-width:280px;min-height:220px;max-width:100%;max-height:80vh;box-sizing:border-box;position:relative;}
      #live-market-chart.chart-expanded{position:fixed;inset:10px;z-index:99999;width:auto!important;height:auto!important;max-width:none;max-height:none;border-radius:12px;box-shadow:0 12px 40px rgba(0,0,0,.45);}
      #live-market-chart .chart-bar{height:38px;min-height:38px;display:flex;align-items:center;justify-content:flex-start;gap:10px;padding:0 8px;background:#111827;color:#e5e7eb;font-size:12px;font-weight:900;letter-spacing:.25px;box-sizing:border-box;}
      #live-market-chart .chart-bar .chart-title{display:block;white-space:nowrap;margin:0;color:#f8fafc;font-size:13px;}
      #live-market-chart .chart-bar .chart-price{margin-left:auto;color:#cbd5e1;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
      #live-market-chart .chart-bar #chart-full-view{display:block;flex:0 0 auto;font-size:11px;line-height:1;padding:7px 9px;border-radius:7px;background:#2563eb;color:#fff;border:0;font-weight:900;cursor:pointer;touch-action:manipulation;}
      #live-market-chart .chart-canvas-wrap{position:relative;flex:1;min-height:0;width:100%;overflow:hidden;border-radius:0 0 7px 7px;background:#0b1220;touch-action:none;cursor:grab;}
      #live-market-chart .chart-canvas-wrap:active{cursor:grabbing;}
      #live-market-chart canvas{display:block;width:100%;height:100%;}
      #live-market-chart .chart-status{padding:7px 10px;font-size:11px;color:#94a3b8;background:#111827;min-height:28px;box-sizing:border-box;}
      @media(max-width:850px){#auto-chart-row{gap:7px;padding-bottom:2px;}#live-market-chart{flex-basis:100%;height:320px;}}
      @media(max-width:600px){#auto-chart-row{gap:6px;}#live-market-chart{width:100%;height:300px;min-height:220px;}#live-market-chart.chart-expanded{inset:0;border-radius:0;}#live-market-chart .chart-bar{height:40px;min-height:40px;}#live-market-chart .chart-bar .chart-price{max-width:48%;font-size:10px;}#live-market-chart .chart-bar #chart-full-view{font-size:10px;padding:6px 8px;}}
    `;

    ensureLayout();
    if (!window.__autoChartObserver) {
      window.__autoChartObserver = new MutationObserver(() => ensureLayout());
      window.__autoChartObserver.observe(document.body, {childList:true, subtree:true});
    }
    window.addEventListener('resize', ensureLayout, {passive:true});
    setTimeout(ensureLayout, 100);
    setTimeout(ensureLayout, 500);
    setTimeout(() => window.dispatchEvent(new Event('resize')), 120);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true}); else mount();
})();
