(() => {
  'use strict';

  const content = document.getElementById('news-content');
  if (!content) return;

  const NEWS_KEY = 'mmc_news_lkg_v4:';
  const DIR_KEY = 'mmc_news_direction_v4:';
  const MAX_PAST_MS = 24 * 60 * 60 * 1000;
  const panel = document.getElementById('news-panel');
  let savedScrollTop = panel ? panel.scrollTop : 0;

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

  const timeOf = (node) => {
    const m = (node?.textContent || '').match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/);
    return m ? m[0] : '';
  };

  const allNews = () => Array.from(content.querySelectorAll(':scope > .news-alert, :scope > .news-list li'))
    .filter(node => !node.closest('#important-news-hero'))
    .map(node => ({node, ms: Date.parse(timeOf(node))}))
    .filter(x => Number.isFinite(x.ms))
    .sort((a, b) => a.ms - b.ms);

  const importantNews = () => allNews().filter(x => x.node.classList.contains('news-impact-high') || x.node.classList.contains('news-impact-medium'));

  function currentSource() {
    return importantNews()[0]?.node || null;
  }

  function saveNews() {
    const source = currentSource();
    if (!source || !pair()) return;
    const time = timeOf(source);
    if (!time) return;
    write(newsKey(), {html: source.outerHTML, eventTime: time, savedAt: Date.now()});
  }

  function restoreNews() {
    // Do not replace a fresh regular-news list with an old high-impact snapshot.
    if (allNews().length) return;
    if (!pair()) return;
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
    content.appendChild(node);
  }

  function saveDirection() {
    const source = currentSource();
    if (!source || !pair()) return;
    const time = timeOf(source);
    const directionNodes = document.querySelectorAll('#important-news-hero .important-news-direction, #important-news-status .ins-direction');
    let direction = '';
    directionNodes.forEach(node => {
      const m = (node.textContent || '').match(/\b(UP|DOWN)\b/i);
      if (m) direction = m[1].toUpperCase();
    });
    if (!direction || !time) return;
    write(directionKey(), {eventTime: time, direction, savedAt: Date.now()});
  }

  function applyDirection() {
    const source = currentSource();
    const saved = read(directionKey());
    if (!source || !saved?.eventTime || !saved.direction || timeOf(source) !== saved.eventTime) return;
    const direction = saved.direction === 'UP' ? 'UP' : saved.direction === 'DOWN' ? 'DOWN' : '';
    if (!direction) return;
    const text = direction === 'UP' ? '⬆ UP — উপরে' : '⬇ DOWN — নিচে';
    document.querySelectorAll('#important-news-hero .important-news-direction, #important-news-status .ins-direction').forEach(node => {
      const classes = node.className.replace(/\b(up|down|wait)\b/gi, '').trim();
      const cls = `${classes} ${direction.toLowerCase()}`.trim();
      if (node.className !== cls) node.className = cls;
      if (node.textContent !== text) node.textContent = text;
    });
  }

  function clearOldDirectionForNewEvent() {
    const source = currentSource();
    const saved = read(directionKey());
    if (!source || !saved?.eventTime || timeOf(source) === saved.eventTime) return;
    try { localStorage.removeItem(directionKey()); } catch (_) {}
  }

  function markLkg(source) {
    if (!source || source.dataset.mmcLkg !== '1') return;
    const title = source.querySelector('strong');
    if (title && !title.textContent.includes('Last Known Good')) {
      title.textContent = `🟡 Last Known Good — ${title.textContent.replace(/^🚨\s*/, '')}`;
    }
  }

  function restorePanelScroll() {
    if (!panel) return;
    requestAnimationFrame(() => {
      if (Math.abs(panel.scrollTop - savedScrollTop) > 1) panel.scrollTop = savedScrollTop;
    });
  }

  function tick() {
    if (!pair()) return;
    restoreNews();
    const source = currentSource();
    if (!source) return;
    clearOldDirectionForNewEvent();
    markLkg(source);
    saveNews();
    applyDirection();
    saveDirection();
    restorePanelScroll();
  }

  if (panel) panel.addEventListener('scroll', () => { savedScrollTop = panel.scrollTop; }, {passive:true});

  tick();
  window.setInterval(tick, 1000);
  if ('MutationObserver' in window) {
    let timer = null;
    const observer = new MutationObserver(() => {
      window.clearTimeout(timer);
      window.requestAnimationFrame(() => { if (panel) panel.scrollTop = savedScrollTop; });
      timer = window.setTimeout(tick, 80);
    });
    observer.observe(content, {childList: true, subtree: true});
  }
  document.getElementById('pair')?.addEventListener('change', () => window.setTimeout(tick, 100));
  document.getElementById('mode')?.addEventListener('change', () => window.setTimeout(tick, 100));
})();
