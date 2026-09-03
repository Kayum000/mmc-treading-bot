(() => {
  'use strict';

  // The previous persistence implementation used v3 keys and could restore a
  // snapshot over the live News hero. Remove those legacy keys before the
  // deferred candle_timer.js starts, so only this v4 implementation is active.
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
  const MAX_PAST_MS = 5 * 60 * 1000;

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
    content.innerHTML = '';
    content.appendChild(node);
  }

  function countdown(node) {
    const count = node?.querySelector('.news-count');
    if (!count) return;
    const ms = Date.parse(eventTime(node));
    if (!Number.isFinite(ms)) return;
    const seconds = Math.max(0, Math.ceil((ms - Date.now()) / 1000));
    count.textContent = seconds <= 0 ? '⏱ নিউজের নির্ধারিত সময় পার হয়েছে' : `⏱ আর ${Math.floor(seconds / 60)} মিনিট ${seconds % 60} সেকেন্ড`;
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

  function tick() {
    if (!pair()) return;
    restoreNews();
    const source = currentSource();
    if (!source) return;
    clearOldDirectionForNewEvent();
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
