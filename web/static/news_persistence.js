(() => {
  'use strict';

  const content = document.getElementById('news-content');
  if (!content) return;

  const NEWS_KEY = 'mmc_news_lkg_v5:';
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
    .filter(x => Number.isFinite(x.ms) && x.ms >= Date.now() - 60 * 1000)
    .sort((a, b) => a.ms - b.ms);

  const importantNews = () => allNews().filter(x => x.node.classList.contains('news-impact-high') || x.node.classList.contains('news-impact-medium'));

  function currentSource() {
    return importantNews()[0]?.node || null;
  }

  // The candle timer can react to its own DOM updates. Cache the real
  // /news-direction response for 30 seconds, keyed by the actual event,
  // so repeated observer calls never hammer the backend or lose a real UP/DOWN result.
  const nativeFetch = window.fetch.bind(window);
  let directionCache = null;
  let directionInFlight = null;

  function directionRequestKey(url) {
    const source = currentSource();
    return `${url}|${mode()}|${pair()}|${source ? timeOf(source) : ''}`;
  }

  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : (input?.url || '');
    if (!url.includes('/news-direction')) return nativeFetch(input, init);

    const key = directionRequestKey(url);
    const now = Date.now();
    if (directionCache && directionCache.key === key && now - directionCache.at < 30000) {
      return Promise.resolve(new Response(JSON.stringify(directionCache.data), {
        status: 200,
        headers: {'Content-Type': 'application/json'}
      }));
    }
    if (directionInFlight && directionCache?.key === key) return directionInFlight;

    directionInFlight = nativeFetch(input, init)
      .then(async response => {
        let data = null;
        try { data = await response.clone().json(); } catch (_) {}
        if (data) directionCache = {key, at: Date.now(), data};
        return response;
      })
      .finally(() => { directionInFlight = null; });
    return directionInFlight;
  };

  // Keep the yellow nearest-news box compact. The normal News Events list
  // remains underneath, so USD pairs can show every upcoming USD event.
  if (!document.getElementById('news-compact-stability')) {
    const compactStyle = document.createElement('style');
    compactStyle.id = 'news-compact-stability';
    compactStyle.textContent = `
      #important-news-hero{padding:7px 9px!important;margin-bottom:7px!important}
      #important-news-hero .important-news-heading{font-size:17px!important;margin-bottom:3px!important}
      #important-news-hero .important-news-title{font-size:15px!important;margin:3px 0!important}
      #important-news-hero .important-news-time{font-size:12px!important;margin:3px 0!important;padding:3px 5px!important}
      #important-news-hero .important-news-count{font-size:12px!important;margin:3px 0!important}
      #important-news-hero .important-news-direction{font-size:19px!important;margin:3px 0!important;padding:3px!important}
      #important-news-hero .important-news-queue-label{font-size:11px!important;margin:4px 0 2px!important}
      #important-news-hero .important-news-queue{max-height:70px!important;gap:3px!important}
      #important-news-hero .important-news-queue-item{padding:3px 5px!important;font-size:11px!important;line-height:1.15!important}
      #important-news-hero .important-news-queue-item strong{font-size:10px!important;margin-bottom:1px!important}
      #important-news-hero .important-news-queue-item span{font-size:10px!important;margin-top:1px!important}
      #important-news-hero .important-news-source{font-size:10px!important;margin-top:2px!important}
    `;
    document.head.appendChild(compactStyle);
  }

  // renderNews() runs every 30 seconds. If the event timestamps did not change,
  // ignore the innerHTML assignment so the list does not visibly jump.
  const nativeInnerHTML = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
  const eventSignature = (html) => {
    const text = String(html || '');
    const matches = text.match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/g) || [];
    return matches.join('|');
  };
  let lastRenderedSignature = eventSignature(content.innerHTML);
  if (nativeInnerHTML?.get && nativeInnerHTML?.set) {
    try {
      Object.defineProperty(content, 'innerHTML', {
        configurable: true,
        get() { return nativeInnerHTML.get.call(content); },
        set(value) {
          const nextSignature = eventSignature(value);
          if (nextSignature && nextSignature === lastRenderedSignature) return;
          lastRenderedSignature = nextSignature;
          nativeInnerHTML.set.call(content, value);
        },
      });
    } catch (_) {}
  }

  function saveNews() {
    const newsNodes = Array.from(content.querySelectorAll(':scope > .news-alert, :scope > .news-list'))
      .filter(node => !node.closest('#important-news-hero'));
    if (!newsNodes.length || !pair()) return;
    const times = allNews().map(x => timeOf(x.node)).filter(Boolean);
    if (!times.length) return;
    write(newsKey(), {
      html: newsNodes.map(node => node.outerHTML).join(''),
      eventTimes: times,
      savedAt: Date.now()
    });
  }

  function restoreNews() {
    // Never replace a fresh, complete list with an old snapshot.
    if (allNews().length) return;
    if (!pair()) return;
    const snapshot = read(newsKey());
    if (!snapshot?.html || !Array.isArray(snapshot.eventTimes) || !snapshot.eventTimes.length) return;
    const newest = Math.max(...snapshot.eventTimes.map(Date.parse).filter(Number.isFinite));
    if (!Number.isFinite(newest) || newest < Date.now() - MAX_PAST_MS) return;

    const holder = document.createElement('div');
    holder.innerHTML = snapshot.html;
    Array.from(holder.children).forEach(node => {
      node.dataset.mmcLkg = '1';
      node.dataset.mmcLkgSavedAt = String(snapshot.savedAt || '');
      content.appendChild(node);
    });
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

  function markLkgNodes() {
    Array.from(content.querySelectorAll(':scope > .news-alert, :scope > .news-list li'))
      .filter(node => node.dataset.mmcLkg === '1')
      .forEach(node => {
        const title = node.querySelector('strong');
        if (title && !title.textContent.includes('Last Known Good')) {
          title.textContent = `🟡 Last Known Good — ${title.textContent.replace(/^🚨\s*/, '')}`;
        }
      });
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
    markLkgNodes();
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
