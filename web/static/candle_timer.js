(() => {
  'use strict';

  const pad = (v) => String(v).padStart(2, '0');
  let directionRequestInFlight = false;
  let lastDirectionKey = '';
  let lastDirectionData = null;
  let lastHeroEventKey = '';
  let lastHeroQueueKey = '';

  function renderClock() {
    const el = document.querySelector('[data-bd-clock]');
    if (!el) return;
    const now = new Date();
    const bd = new Date(now.getTime() + 6 * 60 * 60 * 1000);
    el.textContent = `${pad(bd.getUTCHours())}:${pad(bd.getUTCMinutes())}:${pad(bd.getUTCSeconds())}`;
  }

  function renderEntryCountdown() {
    const el = document.querySelector('[data-entry-timer]');
    if (!el) return;
    const at = Date.parse(el.dataset.entryAt || '');
    if (!Number.isFinite(at)) return;
    const seconds = Math.max(0, Math.ceil((at - Date.now()) / 1000));
    const m = Math.floor(seconds / 60), s = seconds % 60;
    const text = seconds > 0 ? `${pad(m)}:${pad(s)}` : '00:00 — ENTRY NOW';
    if (el.textContent !== text) el.textContent = text;
    el.setAttribute('aria-label', seconds > 0 ? `Entry starts in ${m} minutes ${s} seconds` : 'Entry time reached');
  }

  function injectStyles() {
    if (document.getElementById('important-news-styles')) return;
    const style = document.createElement('style');
    style.id = 'important-news-styles';
    style.textContent = `
      #important-news-hero{margin:0 0 8px;padding:10px;border:2px solid #f59e0b;border-radius:11px;background:#fff8dc;box-shadow:0 2px 8px rgba(0,0,0,.06)}
      #important-news-hero .important-news-heading{font-size:19px;font-weight:900;margin-bottom:5px;color:#9a5b00}
      #important-news-hero .important-news-title{font-size:17px;font-weight:900;line-height:1.3;margin:4px 0}
      #important-news-hero .important-news-time{font-size:14px;font-weight:900;line-height:1.3;margin:5px 0;padding:5px 7px;border-radius:8px;background:#fff;border:1px solid #f3c66b}
      #important-news-hero .important-news-count{font-size:14px;font-weight:900;margin:4px 0}
      #important-news-hero .important-news-direction{display:flex;align-items:center;justify-content:center;min-height:0;margin:5px 0;padding:5px;border-radius:9px;font-size:24px;font-weight:1000;letter-spacing:.5px;border:2px solid #cbd5e1;background:#f8fafc}
      #important-news-hero .important-news-direction.up{color:#15803d;border-color:#86efac;background:#f0fdf4}
      #important-news-hero .important-news-direction.down{color:#dc2626;border-color:#fca5a5;background:#fef2f2}
      #important-news-hero .important-news-direction.wait{color:#92400e;border-color:#fcd34d;background:#fffbeb}
      #important-news-hero .important-news-source{font-size:11px;color:#64748b;margin-top:4px}
      #important-news-hero .important-news-queue-label{font-size:12px;font-weight:900;color:#9a5b00;margin:7px 0 4px}
      #important-news-hero .important-news-queue{display:flex;flex-direction:column;gap:4px;max-height:190px;overflow:auto;padding-right:2px}
      #important-news-hero .important-news-queue-item{padding:5px 7px;border:1px solid #f3c66b;border-radius:7px;background:#fff;font-size:12px;line-height:1.25}
      #important-news-hero .important-news-queue-item.nearest{border:2px solid #dc2626;background:#fff7ed}
      #important-news-hero .important-news-queue-item strong{display:block;font-size:11px;margin-bottom:2px}
      #important-news-hero .important-news-queue-item span{display:block;font-size:11px;font-weight:800;margin-top:2px}
      #important-news-status{margin:8px 0 3px;padding:9px;border:2px solid #f59e0b;border-radius:9px;background:#fff8dc}
      #important-news-status .ins-heading{font-size:17px;font-weight:900;color:#9a5b00;margin-bottom:4px}
      #important-news-status .ins-title{font-size:15px;font-weight:900;line-height:1.3;margin-bottom:4px}
      #important-news-status .ins-time{font-size:13px;font-weight:900;line-height:1.3}
      #important-news-status .ins-count{font-size:14px;font-weight:900;margin-top:3px}
      #important-news-status .ins-direction{font-size:20px;font-weight:1000;text-align:center;margin-top:5px;padding:5px;border-radius:8px;border:2px solid #cbd5e1;background:#fff}
      #important-news-status .ins-direction.up{color:#15803d;border-color:#86efac;background:#f0fdf4}
      #important-news-status .ins-direction.down{color:#dc2626;border-color:#fca5a5;background:#fef2f2}
      #important-news-status .ins-direction.wait{color:#92400e;border-color:#fcd34d;background:#fffbeb}
      #important-news-status .ins-meta{font-size:11px;line-height:1.3;color:#334155;margin-top:4px}
      @media(max-width:600px){#important-news-hero{padding:9px}#important-news-hero .important-news-heading{font-size:18px}#important-news-hero .important-news-title{font-size:16px}#important-news-hero .important-news-time{font-size:13px}#important-news-hero .important-news-direction{font-size:22px}}
    `;
    document.head.appendChild(style);
  }

  function escapeText(v) {
    return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function eventTime(node) {
    const m = (node?.textContent || '').match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/);
    return m ? m[0] : '';
  }

  function titleOf(node) {
    const strong = node?.querySelector('strong');
    let title = strong ? strong.textContent.trim() : (node?.textContent || '').trim();
    title = title.replace(/^🚨\s*/, '').replace(/^[^—]+—\s*/, '');
    return title || 'নির্ধারিত নিউজ';
  }

  function allNewsSources(content) {
    if (!content) return [];
    return Array.from(content.querySelectorAll(':scope > .news-alert, :scope > .news-list li'))
      .filter(node => !node.closest('#important-news-hero'))
      .map(node => ({node, ms: Date.parse(eventTime(node))}))
      .filter(x => Number.isFinite(x.ms) && x.ms >= Date.now() - 60 * 1000)
      .sort((a, b) => a.ms - b.ms);
  }

  function importantSources(content) {
    return allNewsSources(content).filter(x => x.node.classList.contains('news-impact-high') || x.node.classList.contains('news-impact-medium'));
  }

  function formatBd(iso) {
    const ms = Date.parse(iso);
    if (!Number.isFinite(ms)) return '';
    const bd = new Date(ms + 6 * 60 * 60 * 1000);
    return `${bd.getUTCFullYear()}-${pad(bd.getUTCMonth()+1)}-${pad(bd.getUTCDate())} ${pad(bd.getUTCHours())}:${pad(bd.getUTCMinutes())}:${pad(bd.getUTCSeconds())} বাংলাদেশ সময়`;
  }

  function countdownText(ms) {
    const seconds = Math.max(0, Math.ceil((ms - Date.now()) / 1000));
    if (seconds <= 0) return 'সময় পার হয়েছে';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `আর ${h} ঘণ্টা ${m} মিনিট`;
    return `আর ${m} মিনিট ${s} সেকেন্ড`;
  }

  function directionForSource(source) {
    if (!source || !lastDirectionData?.event) return null;
    return eventTime(source) === String(lastDirectionData.event.event_time_utc || '') ? lastDirectionData : null;
  }

  function ensureStatusBox() {
    const panel = document.getElementById('market-status-panel');
    if (!panel) return null;
    let box = document.getElementById('important-news-status');
    if (!box) {
      box = document.createElement('div');
      box.id = 'important-news-status';
      const note = panel.querySelector('.status-note');
      if (note) panel.insertBefore(box, note); else panel.appendChild(box);
    }
    return box;
  }

  function updateStatusImportant(source, directionData) {
    const panel = document.getElementById('market-status-panel');
    if (!panel) return;
    let box = document.getElementById('important-news-status');
    if (!source) { if (box) box.remove(); return; }
    box = ensureStatusBox();
    const t = eventTime(source);
    const direction = String(directionData?.event?.direction || 'WAIT').toUpperCase();
    const dirText = direction === 'UP' ? '⬆ UP — উপরে' : direction === 'DOWN' ? '⬇ DOWN — নিচে' : '⏸ WAIT — দিক এখনো নিশ্চিত নয়';
    const sentiment = directionData?.event?.news_sentiment || {};
    const meta = directionData?.event
      ? `Sentiment: ${escapeText(sentiment.label_bn || 'তথ্য নেই')} | Score: ${escapeText(sentiment.score ?? '—')} | Articles: ${escapeText(sentiment.articles ?? 0)}<br>${escapeText(directionData.event.direction_basis_bn || 'Alpha Vantage sentiment ভিত্তিক সম্ভাব্য bias।')}<br><strong>এটি নিশ্চিত BUY/SELL prediction নয়।</strong>`
      : 'High-impact নিউজ ৫ মিনিটের মধ্যে এলে Alpha Vantage sentiment দিয়ে Direction বিশ্লেষণ হবে।';
    const key = `${titleOf(source)}|${t}|${direction}|${source.querySelector('.news-count')?.textContent || ''}`;
    if (box.dataset.renderKey === key) return;
    box.innerHTML = `<div class="ins-heading">🚨 পরবর্তী গুরুত্বপূর্ণ নিউজ</div><div class="ins-title">${escapeText(titleOf(source))}</div><div class="ins-time">🕒 REAL MARKET TIME (UTC): ${escapeText(t)}</div><div class="ins-time">🇧🇩 বাংলাদেশ সময়: ${escapeText(formatBd(t))}</div><div class="ins-count">⏱ ${escapeText(countdownText(Date.parse(t)))}</div><div class="ins-direction ${direction.toLowerCase()}">${dirText}</div><div class="ins-meta">${meta}</div>`;
    box.dataset.renderKey = key;
  }

  function ensureHero() {
    let hero = document.getElementById('important-news-hero');
    if (hero) return hero;
    const content = document.getElementById('news-content');
    if (!content) return null;
    hero = document.createElement('div');
    hero.id = 'important-news-hero';
    hero.setAttribute('role', 'status');
    hero.innerHTML = `
      <div class="important-news-heading">🚨 নিকটতম নিউজ</div>
      <div class="important-news-title"></div>
      <div class="important-news-time"></div>
      <div class="important-news-time important-news-bd"></div>
      <div class="important-news-count"></div>
      <div class="important-news-direction wait">⏸ WAIT — দিক এখনো নিশ্চিত নয়</div>
      <div class="important-news-queue-label">পরের নিউজগুলো — অল্প সময় বাকি থাকা আগে:</div>
      <div class="important-news-queue"></div>
      <div class="important-news-source"></div>
    `;
    content.insertBefore(hero, content.firstChild);
    return hero;
  }

  function renderHero() {
    const content = document.getElementById('news-content');
    if (!content) return;
    injectStyles();
    const items = allNewsSources(content);
    const hero = document.getElementById('important-news-hero');
    if (!items.length) {
      if (hero) hero.remove();
      lastHeroEventKey = '';
      lastHeroQueueKey = '';
      updateStatusImportant(null, null);
      return;
    }

    const first = items[0];
    const firstTime = eventTime(first.node);
    const eventKey = `${firstTime}|${titleOf(first.node)}`;
    const queueKey = items.map(x => `${eventTime(x.node)}|${titleOf(x.node)}|${x.node.className}`).join('||');
    const box = ensureHero();
    if (!box) return;

    const important = importantSources(content);
    const directionSource = important[0]?.node || null;
    updateStatusImportant(directionSource, directionForSource(directionSource));

    if (eventKey !== lastHeroEventKey) {
      lastHeroEventKey = eventKey;
      box.querySelector('.important-news-title').textContent = titleOf(first.node);
      box.querySelector('.important-news-time').textContent = `🕒 REAL MARKET TIME (UTC): ${firstTime}`;
      box.querySelector('.important-news-bd').textContent = `🇧🇩 ${formatBd(firstTime)}`;
    }

    const countNode = box.querySelector('.important-news-count');
    const countText = `⏱ ${countdownText(first.ms)}`;
    if (countNode.textContent !== countText) countNode.textContent = countText;

    const directionData = directionForSource(directionSource);
    const direction = String(directionData?.event?.direction || 'WAIT').toUpperCase();
    const directionNode = box.querySelector('.important-news-direction');
    const directionText = direction === 'UP' ? '⬆ UP — উপরে' : direction === 'DOWN' ? '⬇ DOWN — নিচে' : '⏸ WAIT — দিক এখনো নিশ্চিত নয়';
    const directionClass = `important-news-direction ${direction.toLowerCase()}`;
    if (directionNode.className !== directionClass) directionNode.className = directionClass;
    if (directionNode.textContent !== directionText) directionNode.textContent = directionText;

    if (queueKey !== lastHeroQueueKey) {
      lastHeroQueueKey = queueKey;
      const queue = box.querySelector('.important-news-queue');
      queue.innerHTML = items.map((item, i) => `<div class="important-news-queue-item ${i===0?'nearest':''}"><strong>${i===0?'🔴 সবচেয়ে কাছের':'🕒 পরবর্তী'}</strong><div>${escapeText(titleOf(item.node))}</div><span>UTC: ${escapeText(eventTime(item.node))} — ${escapeText(countdownText(item.ms))}</span></div>`).join('');
      box.querySelector('.important-news-source').textContent = `মোট ${items.length}টি আসন্ন নিউজ • সবগুলো সময় অনুযায়ী সাজানো।`;
    } else {
      const queue = box.querySelector('.important-news-queue');
      Array.from(queue.children).forEach((node, i) => {
        const item = items[i];
        if (!item) return;
        const span = node.querySelector('span');
        const text = `UTC: ${eventTime(item.node)} — ${countdownText(item.ms)}`;
        if (span && span.textContent !== text) span.textContent = text;
      });
    }
  }

  async function checkAlphaDirection() {
    const content = document.getElementById('news-content');
    const important = importantSources(content);
    const source = important[0]?.node;
    if (!source) { updateStatusImportant(null, null); return; }
    const key = `${eventTime(source)}|${document.getElementById('pair')?.value || ''}`;
    if (directionRequestInFlight || (key === lastDirectionKey && lastDirectionData?.needed)) return;
    directionRequestInFlight = true;
    try {
      const response = await fetch('/news-direction', {method:'GET', cache:'no-store', headers:{'Accept':'application/json'}});
      const data = await response.json();
      if (data?.needed) { lastDirectionKey = key; lastDirectionData = data; }
      else { lastDirectionKey = ''; lastDirectionData = null; }
      updateStatusImportant(source, data?.needed ? data : null);
      renderHero();
    } catch (_) {
      updateStatusImportant(source, directionForSource(source));
      renderHero();
    } finally { directionRequestInFlight = false; }
  }

  function render() { renderClock(); renderEntryCountdown(); renderHero(); }
  render();
  window.setInterval(render, 1000);
  window.setInterval(checkAlphaDirection, 30000);

  const content = document.getElementById('news-content');
  if (content && 'MutationObserver' in window) {
    let timer = null;
    const observer = new MutationObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => { renderHero(); checkAlphaDirection(); }, 80);
    });
    observer.observe(content, {childList:true, subtree:true});
  }
})();
