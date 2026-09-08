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
  let activeEntry = null;

  const esc = v => String(v ?? '').replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
  const ensurePanel = () => {
    if (panel) return panel;
    panel = document.createElement('div');
    panel.id = 'running-entry-panel';
    panel.style.cssText = 'margin:0 0 12px;padding:10px 12px;border:1px solid #b8cffd;border-radius:10px;background:#f8fbff;font-size:13px;font-weight:800;text-align:center;color:#174ea6;';
    result.parentNode.insertBefore(panel, result);
    return panel;
  };

  function renderActiveEntry() {
    if (!activeEntry) return false;
    const now = Date.now();
    const expiry = Date.parse(activeEntry.expiry_time_utc);
    const left = Math.max(0, Math.ceil((expiry - now) / 1000));
    if (!Number.isFinite(expiry) || left <= 0) {
      activeEntry = null;
      lastEntryKey = '';
      return false;
    }
    const p = ensurePanel();
    const cls = activeEntry.signal === 'BUY' ? 'BUY' : 'SELL';
    const icon = cls === 'BUY' ? '🟢' : '🔴';
    p.innerHTML = `${icon} <strong>${esc(cls)} ENTRY ACTIVE — RUNNING 1M CANDLE</strong><br>` +
      `<span>${esc(activeEntry.pair)} · Entry ${esc(activeEntry.entry_time_bd)} BD · <strong>${left}s</strong> until candle close</span><br>` +
      `<span>Entry price: ${esc(activeEntry.entry_price)} · Window: 20-25s · Signal locked until candle close</span>`;
    return true;
  }

  function updatePanel(d) {
    // Once a BUY/SELL is issued, keep it visible for the remainder of the
    // current candle. WAIT/NO_ENTRY responses must never erase that signal.
    if (renderActiveEntry()) return;
    const p = ensurePanel();
    if (!d || d.unselected) { p.textContent = '1M RUNNING ENTRY: Select a market'; return; }
    if (d.signal === 'WAIT') {
      p.innerHTML = `⏳ 1M RUNNING ANALYSIS — ENTRY WINDOW IN <strong>${esc(d.seconds_until_entry_window)}s</strong>`;
    } else if (d.signal === 'NO_ENTRY') {
      p.innerHTML = `⛔ 1M ENTRY CLOSED — next entry window in <strong>${esc(d.seconds_until_entry_window)}s</strong>`;
    } else if (d.signal === 'NO_TRADE') {
      p.innerHTML = `🛡️ ENTRY WINDOW ACTIVE — ${esc(d.reason || 'Trade protection active')}`;
    } else if (d.signal === 'BUY' || d.signal === 'SELL') {
      activeEntry = d;
      const key = `${d.market_mode}|${d.pair}|${d.candle_time}|${d.signal}`;
      lastEntryKey = key;
      renderActiveEntry();
    } else {
      p.textContent = '1M RUNNING ENTRY — monitoring';
    }
  }

  function renderRunningSignal(d) {
    if (!d || !['BUY','SELL'].includes(d.signal)) return;
    // Keep the detailed result as a snapshot. It is intentionally not cleared
    // when the server moves from 20-25s to NO_ENTRY.
    const key = `${d.market_mode}|${d.pair}|${d.candle_time}|${d.signal}`;
    if (key === lastEntryKey && activeEntry) return;
    lastEntryKey = key;
    activeEntry = d;
    const cls = d.signal === 'BUY' ? 'BUY' : 'SELL';
    result.innerHTML = `<h2>${esc(d.pair)} — ${cls}</h2><div class="entry-box"><div class="entry-title">ENTRY NOW — RUNNING 1-MINUTE CANDLE</div><div class="entry-time">${esc(d.entry_time_bd)}</div><div class="countdown-label">CANDLE EXPIRY</div><div class="countdown" data-entry-timer data-entry-at="${esc(d.expiry_time_utc)}">${esc(d.entry_seconds_remaining)}s</div><div class="price-box"><div class="price-label">RUNNING ENTRY PRICE</div><div class="price">${esc(d.entry_price)}</div></div></div><div class="details"><p><strong>Timeframe:</strong> ${esc(d.timeframe)}</p><p><strong>Entry Window:</strong> ${esc(d.entry_window)}</p><p><strong>Buy score:</strong> ${esc(d.buy_score)}</p><p><strong>Sell score:</strong> ${esc(d.sell_score)}</p><p><strong>Reason & Details:</strong> ${esc(d.reason)}</p></div>`;
    renderActiveEntry();
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
      if (!renderActiveEntry()) ensurePanel().textContent = '1M RUNNING ENTRY — connection retrying…';
    } finally { busy = false; }
  }

  function start() {
    if (timer) clearInterval(timer);
    timer = setInterval(() => {
      renderActiveEntry();
      poll();
    }, 1000);
    poll();
  }
  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
    activeEntry = null;
    lastEntryKey = '';
    if (panel) panel.textContent = 'AUTO SIGNAL OFF';
  }

  auto.addEventListener('change', () => auto.checked ? start() : stop());
  pair.addEventListener('change', () => { activeEntry = null; lastEntryKey = ''; if (auto.checked) poll(); });
  document.querySelectorAll('.mode-btn').forEach(b => b.addEventListener('click', () => { activeEntry = null; lastEntryKey = ''; if (auto.checked) setTimeout(poll, 150); }));
  if (auto.checked) start(); else ensurePanel().textContent = '1M RUNNING ENTRY — AUTO SIGNAL OFF';
})();
