(() => {
  'use strict';
  function mount() {
    const findAuto = () => document.getElementById('auto-signal')?.closest('.auto-row');
    const findResult = () => document.getElementById('result-container');
    let anchor = findAuto() || findResult();
    if (!anchor || !anchor.parentElement) return;

    document.querySelectorAll('#live-market-chart').forEach((node, i) => { if (i > 0) node.remove(); });
    let row = document.getElementById('auto-chart-row');
    if (!row) {
      row = document.createElement('div');
      row.id = 'auto-chart-row';
      row.className = 'auto-chart-row';
      anchor.parentElement.insertBefore(row, anchor);
    }

    function ensureLayout() {
      const current = findAuto() || findResult();
      if (!current || !current.parentElement) return;
      if (current.parentElement !== row) row.appendChild(current);
      let chart = document.getElementById('live-market-chart');
      if (!chart) {
        chart = document.createElement('section');
        chart.id = 'live-market-chart';
        chart.className = 'chart-clean chart-small';
        chart.innerHTML = '<div class="chart-bar"><span>LIVE CHART</span><button type="button" id="chart-full-view">FULL VIEW</button></div><div class="chart-canvas-wrap"></div>';
      }
      if (chart.parentElement !== row) row.appendChild(chart);
      bindFull(chart);
    }

    function bindFull(chart) {
      const full = chart.querySelector('#chart-full-view');
      if (!full || full.dataset.bound === '1') return;
      full.dataset.bound = '1';
      full.onclick = (e) => {
        e.stopPropagation();
        const expanded = chart.classList.contains('chart-expanded');
        chart.classList.toggle('chart-expanded', !expanded);
        chart.classList.toggle('chart-small', expanded);
        full.textContent = expanded ? 'FULL VIEW' : 'EXIT FULL VIEW';
        setTimeout(() => window.dispatchEvent(new Event('resize')), 80);
      };
      chart.ondblclick = (e) => {
        if (e.target === full) return;
        const expanded = chart.classList.contains('chart-expanded');
        chart.classList.toggle('chart-expanded', !expanded);
        chart.classList.toggle('chart-small', expanded);
        full.textContent = expanded ? 'FULL VIEW' : 'EXIT FULL VIEW';
        setTimeout(() => window.dispatchEvent(new Event('resize')), 80);
      };
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
      #live-market-chart{display:inline-flex;flex:0 0 560px;flex-direction:column;margin:0;border:1px solid #334155;border-radius:10px;background:#0b1220;padding:2px;overflow:hidden;resize:both;width:560px;height:92px;min-width:220px;min-height:72px;max-width:calc(100vw - 30px);max-height:70vh;box-sizing:border-box;position:relative;}
      #live-market-chart.chart-clean.chart-small{height:92px;}
      #live-market-chart.chart-clean.chart-expanded{height:360px;width:min(900px,calc(100vw - 30px));flex-basis:min(900px,calc(100vw - 30px));}
      #live-market-chart .chart-bar{height:30px;min-height:30px;display:flex;align-items:center;justify-content:space-between;padding:0 6px 0 8px;background:#111827;color:#cbd5e1;font-size:11px;font-weight:800;letter-spacing:.3px;box-sizing:border-box;}
      #live-market-chart .chart-bar span{display:block;white-space:nowrap;}
      #live-market-chart .chart-bar button{display:block;flex:0 0 auto;font-size:10px;line-height:1;padding:5px 8px;border-radius:6px;background:#2563eb;color:#fff;border:0;font-weight:800;cursor:pointer;touch-action:manipulation;}
      #live-market-chart .chart-canvas-wrap{position:relative;flex:1;min-height:0;width:100%;overflow:hidden;border-radius:0 0 7px 7px;background:#0b1220;}
      #live-market-chart canvas{display:block;width:100%;height:100%;}
      @media(max-width:850px){#auto-chart-row{gap:7px;padding-bottom:2px;}#live-market-chart{flex:0 0 min(520px,calc(100vw - 30px));width:min(520px,calc(100vw - 30px));height:100px;}#live-market-chart.chart-expanded{width:min(700px,calc(100vw - 30px));flex-basis:min(700px,calc(100vw - 30px));height:300px;}}
      @media(max-width:600px){#auto-chart-row{gap:6px;}#live-market-chart{flex-basis:calc(100vw - 55px);width:calc(100vw - 55px);min-width:220px;height:100px;}#live-market-chart.chart-expanded{flex-basis:calc(100vw - 20px);width:calc(100vw - 20px);height:300px;}}
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
