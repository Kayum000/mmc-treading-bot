(() => {
  const KEY_PREFIX = 'mmc_news_lkg_v2:';
  const DIR_PREFIX = 'mmc_news_direction_v2:';
  const content = document.getElementById('news-content');
  if (!content) return;

  const getKey = () => `${KEY_PREFIX}${document.getElementById('mode')?.value || 'real'}:${document.getElementById('pair')?.value || ''}`;
  const getDirKey = () => `${DIR_PREFIX}${document.getElementById('mode')?.value || 'real'}:${document.getElementById('pair')?.value || ''}`;
  const read = (k) => { try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch (_) { return null; } };
  const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} };

  function eventTime(node) {
    const m = (node?.textContent || '').match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/);
    return m ? m[0] : '';
  }

  function sourceNode() {
    return content.querySelector(':scope > .news-alert.news-impact-high, :scope > .news-list li.news-impact-high, :scope > .news-alert.news-impact-medium, :scope > .news-list li.news-impact-medium');
  }

  function saveCurrent() {
    const source = sourceNode();
    if (!source || source.dataset.mmcLkg === '1') return;
    const t = eventTime(source);
    if (!t) return;
    write(getKey(), { html: source.outerHTML, eventTime: t, savedAt: Date.now() });
  }

  function restore() {
    if (sourceNode()) return;
    const snap = read(getKey());
    if (!snap?.html || !snap.eventTime) return;
    const ms = Date.parse(snap.eventTime);
    if (!Number.isFinite(ms) || ms < Date.now() - 5 * 60 * 1000) return;
    const holder = document.createElement('div');
    holder.innerHTML = snap.html;
    const node = holder.firstElementChild;
    if (!node) return;
    node.dataset.mmcLkg = '1';
    content.innerHTML = '';
    content.appendChild(node);
    updateCountdown(node, ms);
  }

  function updateCountdown(node, ms) {
    const n = node?.querySelector('.news-count');
    if (!n) return;
    const sec = Math.max(0, Math.ceil((ms - Date.now()) / 1000));
    n.textContent = sec <= 0 ? '⏱ নিউজের নির্ধারিত সময় পার হয়েছে' : `⏱ আর ${Math.floor(sec / 60)} মিনিট ${sec % 60} সেকেন্ড`;
  }

  function saveDirection() {
    const hero = document.getElementById('important-news-hero');
    const node = hero?.querySelector('.important-news-direction');
    if (!node) return;
    const source = sourceNode() || content.querySelector('[data-mmc-lkg="1"]');
    const t = eventTime(source);
    const m = (node.textContent || '').match(/\b(UP|DOWN)\b/i);
    if (!t || !m) return;
    write(getDirKey(), { eventTime: t, direction: m[1].toUpperCase(), savedAt: Date.now() });
  }

  function restoreDirection() {
    const saved = read(getDirKey());
    if (!saved?.eventTime || !saved.direction) return;
    const source = sourceNode() || content.querySelector('[data-mmcLkg="1"]');
    if (!source || eventTime(source) !== saved.eventTime) return;
    const text = saved.direction === 'UP' ? '⬆ UP — উপরে' : '⬇ DOWN — নিচে';
    document.querySelectorAll('#important-news-hero .important-news-direction, #important-news-status .ins-direction').forEach((node) => {
      node.className = node.className.replace(/\b(up|down|wait)\b/gi, '').trim() + ` ${saved.direction.toLowerCase()}`;
      node.textContent = text;
    });
  }

  function tick() {
    const source = sourceNode() || content.querySelector('[data-mmc-lkg="1"]');
    if (source) {
      const ms = Date.parse(eventTime(source));
      if (Number.isFinite(ms)) updateCountdown(source, ms);
    }
    restore();
    restoreDirection();
  }

  saveCurrent();
  tick();
  window.setInterval(() => { saveCurrent(); tick(); }, 1000);
  const observer = new MutationObserver(() => {
    saveCurrent();
    window.setTimeout(tick, 30);
  });
  observer.observe(content, { childList: true, subtree: true });
  document.getElementById('pair')?.addEventListener('change', () => window.setTimeout(tick, 100));
  document.getElementById('mode')?.addEventListener('change', () => window.setTimeout(tick, 100));
})();
