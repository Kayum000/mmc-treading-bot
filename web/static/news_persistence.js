(() => {
  'use strict';

  // Keep only the v4 persistence format. A saved important-news snapshot is a
  // fallback, not a replacement for fresh calendar data.
  try {
    const legacy = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key && (key.startsWith('mmc_news_lkg_v3:') || key.startsWith('mmc_news_direction_v3:'))) legacy.push(key);
    }
    legacy.forEach((key) => localStorage.removeItem(key));
  } catch (_) {}

  const content = document.getElementById('news-content');
  if (!content) return;

  const NEWS_KEY = 'mmc_news_lkg_v4:';
  const DIR_KEY = 'mmc_news_direction_v4:';
  const MAX_PAST_MS = 24 * 60 * 60 * 1000;

  const read = (key) => {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) { return null; }
  };
  const write = (key, value) => {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
  };

  const mode = () => document.getElementById('mode')?.value || 'real';
  const pair = () => document.getElementById('pair')?.value || '';
  const newsKey = () => `${NEWS_KEY}${mode()}:${pair()}`;
  const directionKey = () => `${DIR_KEY}${mode()}:${pair()}`;

  function eventTime(node) {
    const text = node?.textContent || '';
    const match = text.match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/);
    return match ? match[0] : '';
  }

  function directSource() {
    return content.querySelector(':scope > .news-alert.news-impact-high, :scope > .news-list li.news-impact-high, :scope > .news-alert.news-impact-medium, :scope > .news-list li.news-impact-medium');
  }

  function clonedSource() {
    return content.querySelector('#important-news-hero .important-news-original .important-news-clone');
  }

  function currentSource() {
    return directSource() || clonedSource();
  }

  function saveNews() {
    const source = currentSource();
    if (!source || !pair()) return;
    const time = eventTime(source);
    if (!time || !Number.isFinite(Date.parse(time))) return;
    write(newsKey(), {html: source.outerHTML, eventTime: time, savedAt: Date.now()});
  }

  function restoreNews() {
    if (!pair() || currentSource()) return;
    const snapshot = read(newsKey());
    if (!snapshot?.html || !snapshot.eventTime) return;
    const eventMs = Date.parse(snapshot.eventTime);
    if (!Number.isFinite(eventMs) || eventMs < Date.now() - MAX_PAST_MS) return;
    const holder = document.createElement('div');
    holder.innerHTML = snapshot.html;
    const node = holder.firstElementChild;
    if (!node) return;
    node.dataset.mmcLkg = '1';
    node.dataset.mmcLkgSavedAt = String(snapshot.savedAt || '');
    content.innerHTML = '';
    content.appendChild(node);
  }

  function countdown(node) {
    const count = node?.querySelector('.news-count');
    if (!count) return;
    const ms = Date.parse(eventTime(node));
    if (!Number.isFinite(ms)) return;
    const seconds = Math.ceil((ms - Date.now()) / 1000);
    count.textContent = seconds <= 0
      ? '⏱ নিউজের নির্ধারিত সময় পার হয়েছে — এটি Last Known Good News'
      : `⏱ আর ${Math.floor(seconds / 60)} মিনিট ${seconds % 60} সেকেন্ড`;
  }

  function saveDirection() {
    const source = currentSource();
    if (!source || !pair()) return;
    const time = eventTime(source);
    let direction = '';
    content.querySelectorAll('#important-news-hero .important-news-direction, #important-news-status .ins-direction').forEach((node) => {
      const match = (node.textContent || '').match(/\b(UP|DOWN)\b/i);
      if (match) direction = match[1].toUpperCase();
    });
    if (!direction || !time) return;
    write(directionKey(), {eventTime: time, direction, savedAt: Date.now()});
  }

  function applyDirection() {
    const source = currentSource();
    const saved = read(directionKey());
    if (!source || !saved?.eventTime || !saved.direction || eventTime(source) !== saved.eventTime) return;
    const direction = saved.direction === 'UP' ? 'UP' : saved.direction === 'DOWN' ? 'DOWN' : '';
    if (!direction) return;
    const text = direction === 'UP' ? '⬆ UP — উপরে' : '⬇ DOWN — নিচে';
    content.querySelectorAll('#important-news-hero .important-news-direction, #important-news-status .ins-direction').forEach((node) => {
      node.className = node.className.replace(/\b(up|down|wait)\b/gi, '').trim() + ` ${direction.toLowerCase()}`;
      node.textContent = text;
    });
  }

  function clearOldDirectionForNewEvent() {
    const source = currentSource();
    const saved = read(directionKey());
    if (!source || !saved?.eventTime || eventTime(source) === saved.eventTime) return;
    try { localStorage.removeItem(directionKey()); } catch (_) {}
  }

  function markLkg(source) {
    if (!source || source.dataset.mmcLkg !== '1') return;
    const title = source.querySelector('strong');
    if (title && !title.textContent.includes('Last Known Good')) {
      title.textContent = `🟡 Last Known Good — ${title.textContent.replace(/^🚨\s*/, '')}`;
    }
  }

  function tick() {
    if (!pair()) return;
    restoreNews();
    const source = currentSource();
    if (!source) return;
    clearOldDirectionForNewEvent();
    markLkg(source);
    countdown(source);
    saveNews();
    applyDirection();
    saveDirection();
  }

  tick();
  window.setInterval(tick, 1000);
  if ('MutationObserver' in window) {
    let timer = null;
    const observer = new MutationObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(tick, 40);
    });
    observer.observe(content, {childList: true, subtree: true});
  }
  document.getElementById('pair')?.addEventListener('change', () => window.setTimeout(tick, 100));
  document.getElementById('mode')?.addEventListener('change', () => window.setTimeout(tick, 100));
})();

/* Important-news priority queue: nearest upcoming important news first,
   followed by every later high/medium-impact event in chronological order.
   UI-only: no fetching, signal, or Alpha Vantage logic is changed here. */
(() => {
  'use strict';
  const content = document.getElementById('news-content');
  if (!content) return;

  const timeOf = (node) => {
    const match = (node?.textContent || '').match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/);
    return match ? match[0] : '';
  };

  const titleOf = (node) => {
    const strong = node?.querySelector('strong');
    let title = strong ? strong.textContent.trim() : (node?.textContent || '').trim();
    title = title.replace(/^🚨\s*/, '').replace(/^[^—]+—\s*/, '');
    return title || 'গুরুত্বপূর্ণ নিউজ';
  };

  const importantItems = () => Array.from(content.querySelectorAll(
    ':scope > .news-alert.news-impact-high, :scope > .news-alert.news-impact-medium, :scope > .news-list li.news-impact-high, :scope > .news-list li.news-impact-medium'
  ))
    .filter(node => !node.closest('#important-news-hero'))
    .map(node => ({node, ms: Date.parse(timeOf(node))}))
    .filter(item => Number.isFinite(item.ms))
    .sort((a, b) => a.ms - b.ms);

  function injectQueueStyles() {
    if (document.getElementById('important-news-queue-styles')) return;
    const style = document.createElement('style');
    style.id = 'important-news-queue-styles';
    style.textContent = `
      #important-news-hero .important-news-queue-label{font-size:12px;font-weight:900;color:#9a5b00;margin:7px 0 4px}
      #important-news-hero .important-news-queue{display:flex;flex-direction:column;gap:4px;max-height:220px;overflow:auto;padding-right:2px}
      #important-news-hero .important-news-queue-item{padding:5px 7px;border:1px solid #f3c66b;border-radius:7px;background:#fff;font-size:12px;line-height:1.25}
      #important-news-hero .important-news-queue-item.nearest{border:2px solid #dc2626;background:#fff7ed}
      #important-news-hero .important-news-queue-item strong{display:block;font-size:11px;margin-bottom:2px}
      #important-news-hero .important-news-queue-item span{display:block;font-size:11px;font-weight:800;margin-top:2px}
      #important-news-hero .important-news-queue-item small{display:block;font-size:10px;color:#64748b;margin-top:2px}
    `;
    document.head.appendChild(style);
  }

  function syncQueue() {
    const items = importantItems();
    const hero = document.getElementById('important-news-hero');
    if (!hero || !items.length) return;
    injectQueueStyles();

    const signature = items.map(item => timeOf(item.node)).join('|');
    if (hero.dataset.newsQueueSignature === signature) return;

    const first = items[0].node;
    const firstTime = timeOf(first);
    const firstTitle = titleOf(first);
    const firstCount = first.querySelector('.news-count')?.textContent?.trim() || '';
    const directionNode = hero.querySelector('.important-news-direction');
    const directionText = directionNode?.textContent || '⏸ WAIT — দিক এখনো নিশ্চিত নয়';
    const directionClass = directionNode?.className || 'important-news-direction wait';

    const safe = (value) => String(value ?? '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

    let html = `
      <div class="important-news-heading">🚨 গুরুত্বপূর্ণ নিউজ</div>
      <div class="important-news-title">${safe(firstTitle)}</div>
      <div class="important-news-time">🕒 REAL MARKET TIME (UTC): ${safe(firstTime)}</div>
      ${firstCount ? `<div class="important-news-count">${safe(firstCount)}</div>` : ''}
      <div class="${safe(directionClass)}">${safe(directionText)}</div>
      <div class="important-news-queue-label">পরবর্তী গুরুত্বপূর্ণ নিউজ — সময় অনুযায়ী:</div>
      <div class="important-news-queue">`;

    items.forEach((item, index) => {
      const node = item.node;
      const title = titleOf(node);
      const time = timeOf(node);
      const count = node.querySelector('.news-count')?.textContent?.trim() || '';
      html += `<div class="important-news-queue-item ${index === 0 ? 'nearest' : ''}"><strong>${index === 0 ? '🔴 সবচেয়ে কাছের নিউজ' : '🕒 পরবর্তী নিউজ'}</strong><div>${safe(title)}</div><span>UTC: ${safe(time)}${count ? ` — ${safe(count)}` : ''}</span></div>`;
    });

    html += `</div><div class="important-news-source">সব গুরুত্বপূর্ণ নিউজ আগে সবচেয়ে কম সময় বাকি থাকা নিউজ দিয়ে শুরু হবে, তারপর একে একে পরেরগুলো দেখাবে।</div>`;
    hero.innerHTML = html;
    hero.dataset.newsQueueSignature = signature;
  }

  window.setInterval(syncQueue, 300);
  syncQueue();
})();
