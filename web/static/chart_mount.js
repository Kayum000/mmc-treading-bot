(() => {
  'use strict';
  function mount() {
    const result = document.getElementById('result-container');
    if (!result) return;

    // Keep exactly one chart mount. Remove any legacy/duplicate mounts left by older UI builds.
    document.querySelectorAll('#live-market-chart').forEach((node, i) => { if (i > 0) node.remove(); });
    let chart = document.getElementById('live-market-chart');
    if (!chart) {
      chart = document.createElement('section');
      chart.id = 'live-market-chart';
      result.parentElement.insertBefore(chart, result.nextSibling);
    }
    chart.className = 'chart-clean chart-expanded';
    chart.title = 'Drag the corner to resize. Double-click to switch size.';
    chart.innerHTML = '<div class="chart-canvas-wrap"></div>';

    let style = document.getElementById('live-market-chart-style');
    if (!style) {
      style = document.createElement('style');
      style.id = 'live-market-chart-style';
      document.head.appendChild(style);
    }
    style.textContent = `
      #live-market-chart{margin-top:10px;border:1px solid #334155;border-radius:10px;background:#0b1220;padding:2px;overflow:hidden;resize:both;min-width:260px;width:100%;height:360px;min-height:70px;max-width:100%;max-height:70vh;box-sizing:border-box;position:relative;}
      #live-market-chart.chart-clean.chart-small{height:90px;}
      #live-market-chart.chart-clean.chart-expanded{height:360px;}
      #live-market-chart .chart-canvas-wrap{position:relative;width:100%;height:100%;overflow:hidden;border-radius:7px;background:#0b1220;}
      #live-market-chart canvas{display:block;width:100%;height:100%;}
      @media(max-width:600px){#live-market-chart{height:300px;min-width:220px;}#live-market-chart.chart-clean.chart-small{height:80px;}}
    `;

    chart.ondblclick = () => {
      chart.classList.toggle('chart-small');
      chart.classList.toggle('chart-expanded');
      setTimeout(() => window.dispatchEvent(new Event('resize')), 80);
    };
    setTimeout(() => window.dispatchEvent(new Event('resize')), 50);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true}); else mount();
})();
