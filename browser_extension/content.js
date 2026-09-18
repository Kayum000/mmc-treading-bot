(() => {
  "use strict";
  if (window.__MMC_FLOATING_LOADED__) return;
  const host = location.hostname.toLowerCase();
  if (!/(^|\\.)quotex\\.(com|io)$/.test(host) && !/(^|\\.)qxbroker\\.com$/.test(host) && !/(^|\\.)market-qx\\.(info|trade|pro)$/.test(host)) return;
  window.__MMC_FLOATING_LOADED__ = true;

  const BOT_URL = "https://mmc-treading-bot.onrender.com";
  const OTC_PAIRS = ["EURUSD OTC","GBPUSD OTC","USDJPY OTC","AUDUSD OTC","GBPJPY OTC","EURJPY OTC","EURGBP OTC","EURCHF OTC","EURCAD OTC","EURAUD OTC","AUDJPY OTC","AUDCHF OTC","AUDCAD OTC","AUDNZD OTC","GBPAUD OTC","GBPCAD OTC","GBPCHF OTC","NZDUSD OTC","NZDJPY OTC","NZDCHF OTC","USDCAD OTC","USDCHF OTC","USDMXN OTC","USDINR OTC","USDARS OTC"];
  const REAL_PAIRS = ["EUR/USD","GBP/USD","USD/JPY","AUD/USD","GBP/JPY","EUR/JPY","EUR/GBP","EUR/CHF","EUR/CAD","EUR/AUD","AUD/JPY","AUD/CHF","AUD/CAD","AUD/NZD","GBP/AUD","GBP/CAD","GBP/CHF","NZD/USD","NZD/JPY","NZD/CHF","USD/CAD","USD/CHF","USD/MXN","USD/INR","USD/ARS"];

  function normalizeMarket(text) {
    const raw = String(text || "").toUpperCase();
    const compact = raw.replace(/[^A-Z0-9]/g, "");
    for (const pair of OTC_PAIRS) {
      const base = pair.replace(/[^A-Z]/g, "").replace(/OTC$/, "");
      if (compact.includes(base) && compact.includes("OTC")) return {mode:"quotex_otc", pair};
    }
    for (const pair of REAL_PAIRS) {
      const base = pair.replace(/[^A-Z]/g, "");
      if (compact.includes(base)) return {mode:"real", pair};
    }
    return null;
  }

  let currentMarket = null, auto = false, timer = null;

  const box = document.createElement("div");
  box.id = "mmc-floating-signal";
  box.innerHTML = `
    <button id="mmc-fs-main">MMC</button>
    <div id="mmc-fs-panel">
      <div id="mmc-fs-title">MMC SIGNAL</div>
      <div id="mmc-fs-market">মার্কেট: শনাক্ত হচ্ছে...</div>
      <button id="mmc-fs-scan">SCAN</button>
      <label><input id="mmc-fs-auto" type="checkbox"> Floating Auto</label>
      <div id="mmc-fs-status">বন্ধ</div>
      <div id="mmc-fs-result"></div>
    </div>`;
  Object.assign(box.style,{position:"fixed",right:"14px",bottom:"90px",zIndex:"2147483647",fontFamily:"Arial,sans-serif"});
  (document.documentElement || document.body).appendChild(box);

  const main=box.querySelector("#mmc-fs-main"), panel=box.querySelector("#mmc-fs-panel");
  const marketEl=box.querySelector("#mmc-fs-market"), scan=box.querySelector("#mmc-fs-scan");
  const autoEl=box.querySelector("#mmc-fs-auto"), status=box.querySelector("#mmc-fs-status"), resultEl=box.querySelector("#mmc-fs-result");
  Object.assign(main.style,{border:"0",borderRadius:"999px",padding:"11px 15px",fontWeight:"800",cursor:"pointer",boxShadow:"0 4px 16px rgba(0,0,0,.35)"});
  Object.assign(panel.style,{display:"none",marginTop:"8px",padding:"12px",width:"210px",borderRadius:"12px",background:"#111827",color:"#fff",boxShadow:"0 6px 22px rgba(0,0,0,.4)",fontSize:"12px"});
  Object.assign(scan.style,{margin:"9px 0",padding:"7px 12px",cursor:"pointer"});
  Object.assign(status.style,{marginTop:"7px"}); Object.assign(resultEl.style,{marginTop:"8px",lineHeight:"1.5"});
  main.onclick=()=>panel.style.display=panel.style.display==="none"?"block":"none";

  function detectMarket() {
    const text = (document.title || "") + "\n" + (document.body ? document.body.innerText : "");
    const detected = normalizeMarket(text.slice(0,50000));
    if (detected) currentMarket = detected;
    marketEl.textContent = "মার্কেট: " + (currentMarket ? currentMarket.pair : "শনাক্ত হয়নি");
    return currentMarket;
  }

  async function getSignal() {
    const market = detectMarket();
    if (!market) { status.textContent="মার্কেট শনাক্ত হয়নি"; return; }
    status.textContent="Signal স্ক্যান হচ্ছে...";
    try {
      const url = BOT_URL + "/floating-signal?mode=" + encodeURIComponent(market.mode) + "&pair=" + encodeURIComponent(market.pair);
      const r = await fetch(url,{cache:"no-store"});
      const d = await r.json();
      if(!r.ok || !d.ok) throw new Error(d.error || "Signal পাওয়া যায়নি");
      const x=d.result||{};
      resultEl.innerHTML="<b>"+(x.signal||"WAIT")+"</b><br>Score: "+(x.score ?? "—")+"/100";
      status.textContent="Signal প্রস্তুত";
    } catch(e) {
      status.textContent="Signal পাওয়া যায়নি";
      resultEl.textContent=e.message||"সংযোগ সমস্যা";
    }
  }

  function disablePageAuto() {
    const existing=document.getElementById("auto-toggle");
    if(existing && existing.checked){
      existing.checked=false;
      existing.dispatchEvent(new Event("change",{bubbles:true}));
    }
  }

  function schedule() {
    clearTimeout(timer);
    if(!auto) return;
    const now=Date.now(), next=Math.floor(now/60000+1)*60000;
    timer=setTimeout(async()=>{ if(auto){ await getSignal(); schedule(); } },Math.max(50,next-now+100));
  }

  scan.onclick=getSignal;
  autoEl.onchange=()=>{
    auto=autoEl.checked; clearTimeout(timer);
    if(auto){ disablePageAuto(); status.textContent="Floating Auto চালু • Existing Auto বন্ধ"; schedule(); }
    else status.textContent="Floating Auto বন্ধ";
  };

  detectMarket();
  setInterval(detectMarket,1000);
  new MutationObserver(detectMarket).observe(document.documentElement,{subtree:true,childList:true,characterData:true});
})();