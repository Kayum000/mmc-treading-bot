(() => {
  'use strict';

  const state = { tool: 'crosshair', drawing: false, start: null, drawings: [], overlay: null };

  const css = `
    #live-market-chart .broker-tools{position:relative;display:inline-block;margin-left:auto}
    #live-market-chart .broker-tools-btn{padding:6px 10px;border-radius:7px;background:#475569;color:#fff;border:1px solid #64748b;font-weight:900;cursor:pointer}
    #live-market-chart .broker-tools-menu{display:none;position:absolute;right:0;top:38px;z-index:30;width:230px;max-height:330px;overflow:auto;padding:8px;border:1px solid #475569;border-radius:10px;background:#0b1220;box-shadow:0 10px 30px rgba(0,0,0,.35)}
    #live-market-chart .broker-tools-menu.open{display:block}
    #live-market-chart .broker-tools-menu button{display:block;width:100%;text-align:left;margin:3px 0;padding:7px 9px;border-radius:7px;background:#1e293b;color:#e2e8f0;border:1px solid #334155;font-size:12px;cursor:pointer}
    #live-market-chart .broker-tools-menu button.active{background:#2563eb;border-color:#2563eb;color:#fff}
    #live-market-chart .broker-tools-menu .tool-group{padding:5px 6px 3px;color:#94a3b8;font-size:10px;font-weight:900;text-transform:uppercase}
    #chart-drawing-overlay{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
    #live-market-chart .chart-canvas-wrap.tool-draw{cursor:crosshair}
    #live-market-chart:fullscreen{width:100vw;height:100vh;margin:0;border:0;border-radius:0;background:#0f172a;display:flex;flex-direction:column}
    #live-market-chart:fullscreen .chart-canvas-wrap{height:auto;flex:1;min-height:0}
    #live-market-chart:fullscreen .chart-controls{flex:none}
  `;

  function inject(){
    if(!document.getElementById('broker-chart-tools-style')){const s=document.createElement('style');s.id='broker-chart-tools-style';s.textContent=css;document.head.appendChild(s);}
  }

  function getWrap(){return document.querySelector('#live-market-chart .chart-canvas-wrap');}

  function moveChartOutsideResult(){
    const chart=document.getElementById('live-market-chart');
    const result=document.getElementById('result-container');
    if(!chart||!result||chart.parentElement!==result)return;
    const parent=result.parentElement;
    if(parent)parent.insertBefore(chart,result.nextSibling);
  }

  function ensureOverlay(){
    const wrap=getWrap(); if(!wrap) return null;
    let c=document.getElementById('chart-drawing-overlay');
    if(!c){c=document.createElement('canvas');c.id='chart-drawing-overlay';c.setAttribute('aria-label','Chart drawing layer');c.style.pointerEvents='none';wrap.appendChild(c);}
    const r=wrap.getBoundingClientRect(),ratio=Math.max(1,window.devicePixelRatio||1);c.width=Math.max(1,Math.floor(r.width*ratio));c.height=Math.max(1,Math.floor(r.height*ratio));c.style.width=r.width+'px';c.style.height=r.height+'px';state.overlay=c;return c;
  }

  function point(e){const wrap=getWrap(),r=wrap.getBoundingClientRect(),ratio=Math.max(1,window.devicePixelRatio||1);return{x:(e.clientX-r.left)*ratio,y:(e.clientY-r.top)*ratio};}

  function redraw(){
    const c=ensureOverlay(); if(!c)return;const ctx=c.getContext('2d'),ratio=Math.max(1,window.devicePixelRatio||1);ctx.clearRect(0,0,c.width,c.height);ctx.lineWidth=1.5*ratio;ctx.setLineDash([]);
    state.drawings.forEach(d=>{ctx.strokeStyle=d.color||'#38bdf8';ctx.fillStyle='rgba(56,189,248,.10)';ctx.beginPath();if(d.type==='h'){ctx.moveTo(0,d.y);ctx.lineTo(c.width,d.y);ctx.stroke();}else if(d.type==='trend'||d.type==='arrow'){ctx.moveTo(d.a.x,d.a.y);ctx.lineTo(d.b.x,d.b.y);ctx.stroke();if(d.type==='arrow'){const ang=Math.atan2(d.b.y-d.a.y,d.b.x-d.a.x),len=10*ratio;ctx.beginPath();ctx.moveTo(d.b.x,d.b.y);ctx.lineTo(d.b.x-len*Math.cos(ang-.5),d.b.y-len*Math.sin(ang-.5));ctx.lineTo(d.b.x-len*Math.cos(ang+.5),d.b.y-len*Math.sin(ang+.5));ctx.closePath();ctx.fillStyle=d.color||'#38bdf8';ctx.fill();}}else if(d.type==='rect'){ctx.rect(d.a.x,d.a.y,d.b.x-d.a.x,d.b.y-d.a.y);ctx.stroke();ctx.fill();}});
  }

  function setTool(tool){state.tool=tool;const menu=document.querySelector('.broker-tools-menu');if(menu)menu.querySelectorAll('[data-btool]').forEach(b=>b.classList.toggle('active',b.dataset.btool===tool));const wrap=getWrap();if(wrap)wrap.classList.toggle('tool-draw',tool!=='none');if(tool==='clear'){state.drawings=[];state.tool='crosshair';redraw();if(menu)menu.querySelectorAll('[data-btool]').forEach(b=>b.classList.toggle('active',b.dataset.btool==='crosshair'));}}

  function addMenu(){
    const chart=document.getElementById('live-market-chart');if(!chart||chart.querySelector('.broker-tools'))return false;inject();
    moveChartOutsideResult();
    const controls=chart.querySelector('.chart-controls');if(!controls)return false;
    const holder=document.createElement('div');holder.className='broker-tools';holder.innerHTML=`<button type="button" class="broker-tools-btn" aria-expanded="false">🛠 TOOLS</button><div class="broker-tools-menu" role="menu"><div class="tool-group">Drawing</div><button type="button" data-btool="crosshair" class="active">✚ Crosshair</button><button type="button" data-btool="h">━ Horizontal Line</button><button type="button" data-btool="trend">╱ Trend Line</button><button type="button" data-btool="rect">▣ Rectangle / Zone</button><button type="button" data-btool="arrow">➜ Arrow / Marker</button><div class="tool-group">Chart</div><button type="button" data-btool="zoom-in">＋ Zoom In</button><button type="button" data-btool="zoom-out">－ Zoom Out</button><button type="button" data-btool="reset">↺ Reset View</button><button type="button" data-btool="fullscreen">⛶ Full Screen</button><div class="tool-group">Analysis</div><button type="button" data-btool="analysis">📊 SMA / EMA Analysis</button><div class="tool-group">Drawings</div><button type="button" data-btool="clear">🧹 Clear Drawings</button></div>`;
    controls.appendChild(holder);
    const btn=holder.querySelector('.broker-tools-btn'),menu=holder.querySelector('.broker-tools-menu');
    btn.addEventListener('click',e=>{e.stopPropagation();const open=menu.classList.toggle('open');btn.setAttribute('aria-expanded',String(open));});
    document.addEventListener('click',e=>{if(!holder.contains(e.target)){menu.classList.remove('open');btn.setAttribute('aria-expanded','false');}});
    holder.querySelectorAll('[data-btool]').forEach(b=>b.addEventListener('click',()=>{
      const t=b.dataset.btool;
      if(t==='zoom-in'||t==='zoom-out'||t==='reset'||t==='analysis'){
        const target=chart.querySelector(`[data-chart-tool="${t}"]`);if(target)target.click();return;
      }
      if(t==='fullscreen'){
        if(document.fullscreenElement)document.exitFullscreen?.();
        else chart.requestFullscreen?.();
        setTimeout(()=>redraw(),100);
        return;
      }
      setTool(t);menu.classList.remove('open');btn.setAttribute('aria-expanded','false');
    }));
    const wrap=getWrap();if(!wrap)return true;ensureOverlay();
    wrap.addEventListener('pointerdown',e=>{const t=state.tool;if(!['h','trend','rect','arrow'].includes(t))return;state.drawing=true;state.start=point(e);});
    wrap.addEventListener('pointerup',e=>{if(!state.drawing)return;const end=point(e),a=state.start,t=state.tool;state.drawing=false;state.start=null;if(t==='h')state.drawings.push({type:'h',y:end.y});else state.drawings.push({type:t,a,b:end});redraw();});
    wrap.addEventListener('pointermove',e=>{if(state.tool!=='crosshair'&&state.tool!=='h')return;const c=ensureOverlay();if(!c)return;const p=point(e),ctx=c.getContext('2d'),ratio=Math.max(1,window.devicePixelRatio||1);redraw();ctx.strokeStyle='rgba(148,163,184,.75)';ctx.lineWidth=ratio;ctx.setLineDash([5*ratio,4*ratio]);ctx.beginPath();ctx.moveTo(p.x,0);ctx.lineTo(p.x,c.height);ctx.stroke();if(state.tool==='h'){ctx.beginPath();ctx.moveTo(0,p.y);ctx.lineTo(c.width,p.y);ctx.stroke();}ctx.setLineDash([]);});
    window.addEventListener('resize',redraw,{passive:true});
    document.addEventListener('fullscreenchange',()=>setTimeout(redraw,80));
    redraw();return true;
  }

  function watch(){
    if(addMenu())return;
    const root=document.getElementById('result-container');if(!root)return;
    const observer=new MutationObserver(()=>{if(addMenu())observer.disconnect();});observer.observe(root,{childList:true,subtree:true});
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',watch,{once:true});else watch();
})();