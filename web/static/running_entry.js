(() => {
  'use strict';
  const auto = document.getElementById('auto-signal');
  const result = document.getElementById('result-container');
  const pair = document.getElementById('pair');
  const mode = document.getElementById('mode');
  if (!auto || !result || !pair || !mode) return;

  let busy = false;
  let lastEntryKey = '';
  let timer = null;
  let panel = null;

  const esc = v => String(v ?? '').replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
  const ensurePanel = () => {
    if (panel) return panel;
    panel = document.createElement('div');
    panel.id = 'running-entry-panel';
    panel.style.cssText = 'margin:0 0 12px;padding:10px 12px;border:1px solid #b8cffd;border-radius:10px;background:#f8fbff;font-size:13px;font-weight:800;text-align:center;color:#174ea6;';
    result.parentNode.insertBefore(panel, result);
    return panel;
  };

  function updatePanel(d) {
    const p = ensurePanel();
    if (!d || d.unselected) { p.textContent = '1M RUNNING ENTRY: Select a market'; return; }
    if (d.signal === 'WAIT') {
      p.innerHTML = `⏳ 1M RUNNING ANALYSIS — ENTRY WINDOW IN <strong>${esc(d.seconds_until_entry_window)}s</strong>`;
    } else if (d.signal === 'NO_ENTRY') {
      p.innerHTML = `⛔ 1M ENTRY CLOSED — next entry window in <strong>${esc(d.seconds_until_entry_window)}s</strong>`;
    } else if (d.signal === 'NO_TRADE') {
      p.innerHTML = `🛡️ ENTRY WINDOW ACTIVE — ${esc(d.reason || 'Trade protection active')}`;
    } else if (d.signal === 'BUY' || d.signal === 'SELL') {
      p.innerHTML = `${d.signal === 'BUY' ? '🟢' : '🔴'} <strong>${esc(d.signal)} ENTRY NOW</strong> — ${esc(d.entry_time_bd)} BD · ${esc(d.entry_seconds_remaining)}s left`;
    } else {
      p.textContent = '1M RUNNING ENTRY — monitoring';
    }
  }

  function renderRunningSignal(d) {
    if (!d || !['BUY','SELL'].includes(d.signal)) return;
    const key = `${d.market_mode}|${d.pair}|${d.candle_time}|${d.signal}`;
    if (key === lastEntryKey) return;
    lastEntryKey = key;
    const cls = d.signal === 'BUY' ? 'BUY' : 'SELL';
    result.innerHTML = `<h2>${esc(d.pair)} — ${cls}</h2><div class="entry-box"><div class="entry-title">ENTRY NOW — RUNNING 1-MINUTE CANDLE</div><div class="entry-time">${esc(d.entry_time_bd)}</div><div class="countdown-label">CANDLE EXPIRY</div><div class="countdown" data-entry-timer data-entry-at="${esc(d.expiry_time_utc)}">00:00</div><div class="price-box"><div class="price-label">RUNNING ENTRY PRICE</div><div class="price">${esc(d.entry_price)}</div></div></div><div class="details"><p><strong>Timeframe:</strong> ${esc(d.timeframe)}</p><p><strong>Entry Window:</strong> ${esc(d.entry_window)}</p><p><strong>Buy score:</strong> ${esc(d.buy_score)}</p><p><strong>Sell score:</strong> ${esc(d.sell_score)}</p><p><strong>Reason & Details:</strong> ${esc(d.reason)}</p></div>`;
  }

  async function poll() {
    if (!auto.checked || !pair.value || !mode.value || busy) return;
    busy = true;
    try {
      const r = await fetch('/running-signal', {method:'GET', cache:'no-store', headers:{'Accept':'application/json'}, credentials:'same-origin'});
      const d = await r.json();
      if (r.ok && d.ok) {
        updatePanel(d);
        renderRunningSignal(d);
      }
    } catch (_) {
      ensurePanel().textContent = '1M RUNNING ENTRY — connection retrying…';
    } finally { busy = false; }
  }

  function start() {
    if (timer) clearInterval(timer);
    timer = setInterval(poll, 1000);
    poll();
  }
  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
    if (panel) panel.textContent = 'AUTO SIGNAL OFF';
  }

  auto.addEventListener('change', () => auto.checked ? start() : stop());
  pair.addEventListener('change', () => { lastEntryKey = ''; if (auto.checked) poll(); });
  document.querySelectorAll('.mode-btn').forEach(b => b.addEventListener('click', () => { lastEntryKey = ''; if (auto.checked) setTimeout(poll, 150); }));
  if (auto.checked) start(); else ensurePanel().textContent = '1M RUNNING ENTRY — AUTO SIGNAL OFF';
})();
