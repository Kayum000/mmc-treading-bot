(() => {
  'use strict';
  function mount() {
    const result = document.getElementById('result-container');
    if (!result || document.getElementById('live-market-chart')) return;
    const chart = document.createElement('section');
    chart.id = 'live-market-chart';
    chart.className = 'chart-compact';
    chart.title = 'Double-click to expand/collapse. Drag the right-bottom corner to resize.';
    chart.innerHTML = '<div class="chart-canvas-wrap"></div>';

    const style = document.createElement('style');
    style.id = 'live-market-chart-style';
    style.textContent = `
      #live-market-chart{margin-top:10px;border:1px solid #334155;border-radius:10px;background:#0b1220;color:#e2e8f0;padding:2px;overflow:hidden;resize:both;min-width:260px;width:100%;height:78px;min-height:56px;max-height:70vh;box-sizing:border-box;position:relative;}
      #live-market-chart.chart-expanded{height:360px;}
      #live-market-chart .chart-canvas-wrap{position:relative;width:100%;height:100%;overflow:hidden;border-radius:7px;background:#0b1220;}
      #live-market-chart.chart-compact .chart-canvas-wrap{height:100%;}
      #live-market-chart.chart-expanded .chart-canvas-wrap{height:100%;}
      #live-market-chart:focus{outline:none;}
      @media(max-width:600px){#live-market-chart{height:68px;min-width:220px;}#live-market-chart.chart-expanded{height:300px;}}
    `;
    document.head.appendChild(style);

    chart.addEventListener('dblclick', () => {
      chart.classList.toggle('chart-compact');
      chart.classList.toggle('chart-expanded');
      setTimeout(() => window.dispatchEvent(new Event('resize')), 80);
    });

    result.parentElement.insertBefore(chart, result.nextSibling);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true}); else mount();
})();
