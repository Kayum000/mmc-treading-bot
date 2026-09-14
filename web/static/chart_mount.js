(() => {
  'use strict';
  function mount() {
    const dashboard=document.querySelector('.dashboard');
    const anchor=document.getElementById('result-container');
    if(!dashboard||!anchor)return;
    let chart=document.getElementById('live-market-chart');
    if(!chart){
      chart=document.createElement('section');
      chart.id='live-market-chart';
      chart.className='chart-clean';
      chart.innerHTML='<div class="chart-bar"><span class="chart-title">LIVE CHART</span><span class="chart-price">—</span><button type="button" id="chart-full-view">FULL VIEW</button></div><div class="chart-canvas-wrap"></div>';
    }
    const legacy=chart.querySelector('#live-market-canvas,.chart-controls,.chart-analysis,.chart-head');
    if(legacy){
      const price=chart.querySelector('.chart-price')?.textContent||'—';
      chart.innerHTML=`<div class="chart-bar"><span class="chart-title">LIVE CHART</span><span class="chart-price">${price}</span><button type="button" id="chart-full-view">FULL VIEW</button></div><div class="chart-canvas-wrap"></div>`;
    }
    let bar=chart.querySelector('.chart-bar');
    if(!bar){bar=document.createElement('div');bar.className='chart-bar';chart.prepend(bar)}
    let title=chart.querySelector('.chart-title');
    if(!title){title=document.createElement('span');title.className='chart-title';title.textContent='LIVE CHART';bar.prepend(title)}
    let price=chart.querySelector('.chart-price');
    if(!price){price=document.createElement('span');price.className='chart-price';price.textContent='—';bar.appendChild(price)}
    let full=document.getElementById('chart-full-view');
    if(!full){full=document.createElement('button');full.type='button';full.id='chart-full-view';full.textContent='FULL VIEW';bar.appendChild(full)}
    if(full.dataset.bound!=='1'){
      full.dataset.bound='1';
      full.onclick=(e)=>{e.preventDefault();e.stopPropagation();const expanded=chart.classList.toggle('chart-expanded');full.textContent=expanded?'EXIT FULL VIEW':'FULL VIEW';setTimeout(()=>window.dispatchEvent(new Event('resize')),80)};
    }
    if(chart.parentElement!==dashboard||chart.previousElementSibling!==anchor)dashboard.insertBefore(chart,document.getElementById('news-panel'));
    let style=document.getElementById('live-market-chart-style');
    if(!style){style=document.createElement('style');style.id='live-market-chart-style';document.head.appendChild(style)}
    style.textContent=`
      .dashboard{grid-template-columns:repeat(3,minmax(0,1fr))!important;grid-auto-flow:row!important;align-items:start!important}
      #live-market-chart{grid-column:1/-1!important;grid-row:auto!important;display:flex;flex-direction:column;margin:0;width:100%;height:390px;min-height:260px;max-width:none;max-height:80vh;box-sizing:border-box;position:relative;overflow:hidden;border:1px solid #19415f;border-radius:12px;background:#071322}
      #live-market-chart .chart-bar{height:46px;min-height:46px;display:flex;align-items:center;gap:10px;padding:0 12px;background:linear-gradient(90deg,#0b2743,#071525);border-bottom:1px solid #173b59;color:#f4f8fd;font-size:12px;font-weight:900}
      #live-market-chart .chart-title{white-space:nowrap}.chart-price{margin-left:auto;color:#39d6b0}.chart-bar #chart-full-view{padding:7px 9px;border-radius:7px;background:#176fd4;color:#fff;border:1px solid #278cff;font-size:9px;font-weight:900;cursor:pointer}
      #live-market-chart .chart-canvas-wrap{position:relative;flex:1;min-height:0;width:100%;overflow:hidden;background:#06111f;touch-action:none;cursor:grab}
      #live-market-chart canvas{display:block;width:100%;height:100%}
      #live-market-chart.chart-expanded{position:fixed;inset:10px;z-index:99999;width:auto!important;height:auto!important;max-width:none;max-height:none}
      @media(max-width:1050px){.dashboard{grid-template-columns:repeat(2,minmax(0,1fr))!important}#live-market-chart{grid-column:1/-1!important}}
      @media(max-width:700px){.dashboard{grid-template-columns:1fr!important}#live-market-chart{grid-column:1!important;height:310px;min-height:220px}#live-market-chart.chart-expanded{inset:0;border-radius:0}}
    `;
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
