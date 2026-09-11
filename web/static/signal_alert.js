(() => {
  let audioContext = null;
  let lastSignalKey = '';

  function ensureAudio() {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return null;
    if (!audioContext) audioContext = new AudioCtx();
    if (audioContext.state === 'suspended') audioContext.resume().catch(() => {});
    return audioContext;
  }
  function tone(ctx, frequency, start, duration, volume) {
    const osc = ctx.createOscillator(); const gain = ctx.createGain();
    osc.type = 'sine'; osc.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(volume, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    osc.connect(gain).connect(ctx.destination); osc.start(start); osc.stop(start + duration + 0.03);
  }
  function playSignalSound(signal) {
    const ctx = ensureAudio(); if (!ctx) return; const now = ctx.currentTime + 0.03;
    if (signal === 'BUY') { tone(ctx, 880, now, 0.16, 0.18); tone(ctx, 1175, now + 0.20, 0.20, 0.18); }
    else if (signal === 'SELL') { tone(ctx, 740, now, 0.16, 0.18); tone(ctx, 587, now + 0.20, 0.20, 0.18); tone(ctx, 440, now + 0.40, 0.24, 0.16); }
  }
  function showBrowserNotification(signal, pair) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    try { new Notification(`MMC ${signal}`, {body: `${pair || 'Market'} — ${signal} signal`}); } catch (_) {}
  }
  window.enableSignalAudio = function () {
    ensureAudio();
    if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission().catch(() => {});
  };
  window.alertForSignal = function (result) {
    if (!result || !result.signal) return;
    const signal = String(result.signal).toUpperCase(); if (signal !== 'BUY' && signal !== 'SELL') return;
    const key = `${result.pair || ''}|${signal}|${result.entry_time_utc || ''}`;
    if (key === lastSignalKey) return; lastSignalKey = key;
    playSignalSound(signal); showBrowserNotification(signal, result.pair);
    if (window.AndroidSignalAlert && typeof window.AndroidSignalAlert.notifySignal === 'function') {
      try { window.AndroidSignalAlert.notifySignal(signal, String(result.pair || 'MMC Live Signal')); } catch (_) {}
    }
  };
  function configureDownloadApp() {
    const link = document.querySelector('.download-app'); if (!link) return;
    const ua = navigator.userAgent || '';
    if (/Android/i.test(ua)) { link.href = 'https://github.com/Kayum000/mmc-treading-bot/releases/download/latest/app-debug.apk'; link.textContent = '📲 Download Android App'; }
    else if (/Windows NT/i.test(ua)) { link.href = 'https://github.com/Kayum000/mmc-treading-bot/releases/download/latest-windows/MMC-Trading-Bot.exe'; link.textContent = '💻 Download Windows App'; }
    else { link.href = 'https://github.com/Kayum000/mmc-treading-bot/releases/download/latest/app-debug.apk'; link.textContent = '📲 Download Android App'; }
  }
  function installQuotexLabels() {
    const labels = ['EURUSD OTC','GBPUSD OTC','USDJPY OTC','AUDUSD OTC','USDCAD OTC','USDCHF OTC','NZDUSD OTC','EURJPY OTC','GBPJPY OTC','XAUUSD OTC'];
    document.querySelectorAll('.mode-btn').forEach(btn => { if (btn.dataset.mode === 'crypto') btn.textContent = 'QUOTEX OTC'; });
    const select = document.getElementById('pair'); if (!select) return;
    const opts = Array.from(select.options).filter(o => o.dataset.market === 'crypto');
    opts.forEach((o, i) => { if (labels[i]) o.textContent = labels[i]; });
    const statusPair = document.getElementById('status-pair');
    const syncStatusPair = () => {
      if (statusPair && select.dataset.marketMode !== 'real' && document.getElementById('mode')?.value === 'crypto' && select.value) {
        const selected = Array.from(select.options).find(o => o.value === select.value);
        if (selected) statusPair.textContent = selected.textContent;
      }
    };
    syncStatusPair();
    setInterval(syncStatusPair, 500);
  }
  function syncSelectedMarket() {
    const mode = document.getElementById('mode')?.value || '';
    const pair = document.getElementById('pair')?.value || '';
    if (!mode || !pair) return;
    const body = new URLSearchParams({mode, pair});
    fetch('/select-market', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'}, body, credentials:'same-origin', cache:'no-store'}).catch(() => {});
  }
  function ensureSignalPanelVisible() {
    const panel = document.getElementById('result-container');
    const status = document.getElementById('market-status-panel');
    const news = document.getElementById('news-panel');
    if (!panel || !status || !news) return;
    if (window.innerWidth <= 850) {
      panel.style.order = '1';
      status.style.order = '2';
      news.style.order = '3';
    } else {
      panel.style.order = '';
      status.style.order = '';
      news.style.order = '';
    }
  }
  function cleanUnwantedAutoStatus() {
    const el = document.getElementById('auto-status'); if (!el) return;
    const unwanted = 'পরের 1-minute candle শুরু হলে signal হবে।';
    if (!el.textContent.includes(unwanted)) return;
    const cleaned = el.textContent.replace(unwanted, '').replace(/\s*—\s*$/, '').trim();
    el.textContent = cleaned || 'AUTO SIGNAL চালু';
  }
  document.addEventListener('DOMContentLoaded', () => {
    configureDownloadApp(); installQuotexLabels(); ensureSignalPanelVisible(); cleanUnwantedAutoStatus();
    window.addEventListener('resize', ensureSignalPanelVisible);
    const target = document.getElementById('auto-status');
    if (target && typeof MutationObserver !== 'undefined') new MutationObserver(cleanUnwantedAutoStatus).observe(target, {childList:true,characterData:true,subtree:true});
    setTimeout(syncSelectedMarket, 800);
    setTimeout(syncSelectedMarket, 2000);
  });
  document.addEventListener('click', () => window.enableSignalAudio(), {once:true});
})();