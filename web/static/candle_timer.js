(() => {
  const bdClock = document.querySelector('[data-bd-clock]');
  const pad = (value) => String(value).padStart(2, '0');
  let enhancingNews = false;
  let directionRequestInFlight = false;
  let lastDirectionKey = '';
  let lastDirectionData = null;

  function renderClock() {
    if (!bdClock) return;
    const now = new Date();
    const bd = new Date(now.getTime() + (6 * 60 * 60 * 1000));
    bdClock.textContent = `${pad(bd.getUTCHours())}:${pad(bd.getUTCMinutes())}:${pad(bd.getUTCSeconds())}`;
  }

  function renderEntryCountdown() {
    const entryTimer = document.querySelector('[data-entry-timer]');
    if (!entryTimer) return;
    const entryAt = Date.parse(entryTimer.dataset.entryAt || '');
    if (!Number.isFinite(entryAt)) return;
    const remainingSeconds = Math.max(0, Math.ceil((entryAt - Date.now()) / 1000));
    const minutes = Math.floor(remainingSeconds / 60);
    const seconds = remainingSeconds % 60;
    entryTimer.textContent = remainingSeconds > 0 ? `${pad(minutes)}:${pad(seconds)}` : '00:00 — ENTRY NOW';
    entryTimer.setAttribute('aria-label', remainingSeconds > 0 ? `Entry starts in ${minutes} minutes ${seconds} seconds` : 'Entry time reached');
  }

  function injectNewsStyles() {
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
      #important-news-hero .important-news-direction.up,#important-news-status .ins-direction.up{color:#15803d;border-color:#86efac;background:#f0fdf4}
      #important-news-hero .important-news-direction.down,#important-news-status .ins-direction.down{color:#dc2626;border-color:#fca5a5;background:#fef2f2}
      #important-news-hero .important-news-direction.wait,#important-news-status .ins-direction.wait{color:#92400e;border-color:#fcd34d;background:#fffbeb}
      #important-news-hero .important-news-source{font-size:11px;color:#64748b;margin-top:4px}
      #important-news-hero .important-news-original{margin-top:5px}
      #important-news-hero .important-news-original .news-pairs{font-size:13px}
      #important-news-hero .important-news-original .news-prediction{font-size:12px}
      #important-news-status{margin:8px 0 3px;padding:9px;border:2px solid #f59e0b;border-radius:9px;background:#fff8dc}
      #important-news-status .ins-heading{font-size:17px;font-weight:900;color:#9a5b00;margin-bottom:4px}
      #important-news-status .ins-title{font-size:15px;font-weight:900;line-height:1.3;margin-bottom:4px}
      #important-news-status .ins-time{font-size:13px;font-weight:900;line-height:1.3}
      #important-news-status .ins-count{font-size:14px;font-weight:900;margin-top:3px}
      #important-news-status .ins-direction{font-size:20px;font-weight:1000;text-align:center;margin-top:5px;padding:5px;border-radius:8px;border:2px solid #cbd5e1;background:#fff}
      #important-news-status .ins-direction.up,#important-news-status .ins-direction.down,#important-news-status .ins-direction.wait{border-width:2px}
      #important-news-status .ins-meta{font-size:11px;line-height:1.3;color:#334155;margin-top:4px}
      @media(max-width:600px){#important-news-hero{padding:9px}#important-news-hero .important-news-heading{font-size:18px}#important-news-hero .important-news-title{font-size:16px}#important-news-hero .important-news-time{font-size:13px}#important-news-hero .important-news-direction{font-size:22px}#important-news-status .ins-heading{font-size:17px}#important-news-status .ins-direction{font-size:21px}}
    `;
    document.head.appendChild(style);
  }

  function extractDirection(node) {
    const text = node?.textContent || '';
    const match = text.match(/DIRECTION\s*:\s*(UP|DOWN|WAIT)/i);
    return match ? match[1].toUpperCase() : 'WAIT';
  }

  function extractEventTime(node) {
    const text = node?.textContent || '';
    const match = text.match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/);
    return match ? match[0] : 'সময় পাওয়া যায়নি';
  }

  function extractTitle(node) {
    if (!node) return 'গুরুত্বপূর্ণ নির্ধারিত নিউজ';
    const alertStrong = node.classList.contains('news-alert') ? node.querySelector('strong') : null;
    if (alertStrong) {
      let title = alertStrong.textContent.trim().replace(/^🚨\s*/, '');
      title = title.replace(/^[^—]+—\s*/, '');
      if (title) return title;
    }
    const text = node.textContent || '';
    const parts = text.split('—').map(v => v.trim()).filter(Boolean);
    if (parts.length >= 3) return parts[2];
    return 'গুরুত্বপূর্ণ নির্ধারিত নিউজ';
  }

  function formatBangladeshTime(iso) {
    const ms = Date.parse(iso);
    if (!Number.isFinite(ms)) return '';
    const bd = new Date(ms + (6 * 60 * 60 * 1000));
    return `${bd.getUTCFullYear()}-${pad(bd.getUTCMonth() + 1)}-${pad(bd.getUTCDate())} ${pad(bd.getUTCHours())}:${pad(bd.getUTCMinutes())}:${pad(bd.getUTCSeconds())} বাংলাদেশ সময়`;
  }

  function escapeText(value) {
    return String(value ?? '').replace(/[&<>\"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
  }

  function getImportantSource(content) {
    return content?.querySelector(':scope > .news-alert.news-impact-high, :scope > .news-list li.news-impact-high, :scope > .news-alert.news-impact-medium, :scope > .news-list li.news-impact-medium');
  }

  function directionForSource(source) {
    if (!source || !lastDirectionData?.event) return null;
    const sourceTime = extractEventTime(source);
    const directionTime = String(lastDirectionData.event.event_time_utc || '');
    return sourceTime === directionTime ? lastDirectionData : null;
  }

  function ensureMarketStatusNewsBox() {
    const panel = document.getElementById('market-status-panel');
    if (!panel) return null;
    let box = document.getElementById('important-news-status');
    if (!box) {
      box = document.createElement('div');
      box.id = 'important-news-status';
      const note = panel.querySelector('.status-note');
      if (note) panel.insertBefore(box, note);
      else panel.appendChild(box);
    }
    return box;
  }

  function updateMarketStatusImportantNews(source, directionData = null) {
    const panel = document.getElementById('market-status-panel');
    if (!panel) return;
    let box = document.getElementById('important-news-status');
    if (!source) {
      if (box) box.remove();
      return;
    }
    box = ensureMarketStatusNewsBox();
    const eventTime = extractEventTime(source);
    const bdTime = formatBangladeshTime(eventTime);
    const title = extractTitle(source);
    const countdown = source.querySelector('.news-count')?.textContent?.trim() || '';
    const event = directionData?.event;
    const direction = String(event?.direction || 'WAIT').toUpperCase();
    const directionText = direction === 'UP' ? '⬆ UP — উপরে' : direction === 'DOWN' ? '⬇ DOWN — নিচে' : '⏸ WAIT — দিক এখনো নিশ্চিত নয়';
    const sentiment = event?.news_sentiment || {};
    const meta = event ? `Sentiment: ${escapeText(sentiment.label_bn || 'তথ্য নেই')} | Score: ${escapeText(sentiment.score ?? '—')} | Articles: ${escapeText(sentiment.articles ?? 0)}<br>${escapeText(event.direction_basis_bn || 'Alpha Vantage sentiment ভিত্তিক সম্ভাব্য bias।')}<br><strong>এটি নিশ্চিত BUY/SELL prediction নয়।</strong>` : 'High-impact নিউজ ৫ মিনিটের মধ্যে এলে Alpha Vantage sentiment দিয়ে Direction বিশ্লেষণ হবে।';
    box.innerHTML = `
      <div class="ins-heading">🚨 গুরুত্বপূর্ণ নিউজ</div>
      <div class="ins-title">${escapeText(title)}</div>
      <div class="ins-time">🕒 REAL MARKET TIME (UTC): ${escapeText(eventTime)}</div>
      ${bdTime ? `<div class="ins-time">🇧🇩 বাংলাদেশ সময়: ${escapeText(bdTime)}</div>` : ''}
      ${countdown ? `<div class="ins-count">⏱ ${escapeText(countdown)}</div>` : ''}
      <div class="ins-direction ${direction.toLowerCase()}">${directionText}</div>
      <div class="ins-meta">${meta}</div>
    `;
  }

  function updateDirectionInYellowBox(data) {
    const content = document.getElementById('news-content');
    const source = getImportantSource(content);
    if (!source) return;
    lastDirectionData = data?.needed ? data : null;
    updateMarketStatusImportantNews(source, directionForSource(source));

    const hero = document.getElementById('important-news-hero');
    if (!hero) return;
    const directionNode = hero.querySelector('.important-news-direction');
    if (!directionNode) return;
    const event = data?.event;
    const direction = String(event?.direction || 'WAIT').toUpperCase();
    directionNode.className = `important-news-direction ${direction.toLowerCase()}`;
    directionNode.textContent = direction === 'UP' ? '⬆ UP — উপরে' : direction === 'DOWN' ? '⬇ DOWN — নিচে' : '⏸ WAIT — দিক এখনো নিশ্চিত নয়';
  }

  async function checkAlphaDirection() {
    const content = document.getElementById('news-content');
    const source = getImportantSource(content);
    if (!source || !source.classList.contains('news-impact-high') && !source.matches('.news-list li.news-impact-high')) return;
    const eventTime = extractEventTime(source);
    const key = `${eventTime}|${document.getElementById('pair')?.value || ''}`;
    // Keep retrying the same event while it is outside the 5-minute direction
    // window. Once Alpha Vantage returns a needed result, lock that event key.
    if (directionRequestInFlight || (key === lastDirectionKey && lastDirectionData?.needed)) return;
    directionRequestInFlight = true;
    try {
      const response = await fetch('/news-direction', {method:'GET', cache:'no-store', headers:{'Accept':'application/json'}});
      const data = await response.json();
      if (data?.needed) {
        lastDirectionKey = key;
        lastDirectionData = data;
      } else if (key !== lastDirectionKey) {
        lastDirectionKey = '';
        lastDirectionData = null;
      }
      updateMarketStatusImportantNews(source, data?.needed ? data : null);
      updateDirectionInYellowBox(data?.needed ? data : null);
    } catch (e) {
      updateMarketStatusImportantNews(source, directionForSource(source));
      updateDirectionInYellowBox(lastDirectionData);
    } finally {
      directionRequestInFlight = false;
    }
  }

  function enhanceImportantNews() {
    if (enhancingNews) return;
    const content = document.getElementById('news-content');
    if (!content) return;
    injectNewsStyles();

    const source = getImportantSource(content);
    if (!source) {
      const oldHero = document.getElementById('important-news-hero');
      if (oldHero) oldHero.remove();
      updateMarketStatusImportantNews(null);
      return;
    }

    const sourceDirection = directionForSource(source);
    updateMarketStatusImportantNews(source, sourceDirection);
    const oldHero = document.getElementById('important-news-hero');
    const eventTime = extractEventTime(source);
    const bdTime = formatBangladeshTime(eventTime);
    const title = extractTitle(source);
    const countdown = source.querySelector('.news-count')?.textContent?.trim() || '';
    const direction = String(sourceDirection?.event?.direction || 'WAIT').toUpperCase();

    enhancingNews = true;
    try {
      if (oldHero) oldHero.remove();
      const hero = document.createElement('div');
      hero.id = 'important-news-hero';
      hero.setAttribute('role', 'status');
      hero.innerHTML = `
        <div class="important-news-heading">🚨 গুরুত্বপূর্ণ নিউজ</div>
        <div class="important-news-title">${escapeText(title)}</div>
        <div class="important-news-time">🕒 REAL MARKET TIME (UTC): ${escapeText(eventTime)}</div>
        ${bdTime ? `<div class="important-news-time">🇧🇩 বাংলাদেশ সময়: ${escapeText(bdTime)}</div>` : ''}
        ${countdown ? `<div class="important-news-count">⏱ ${escapeText(countdown)}</div>` : ''}
        <div class="important-news-direction ${direction.toLowerCase()}">${direction === 'UP' ? '⬆ UP — উপরে' : direction === 'DOWN' ? '⬇ DOWN — নিচে' : '⏸ WAIT — দিক এখনো নিশ্চিত নয়'}</div>
        <div class="important-news-source">Calendar data আলাদা রাখা হয়েছে; high-impact নিউজ ৫ মিনিটের মধ্যে এলে Alpha Vantage শুধু Direction-এর জন্য ব্যবহার হবে।</div>
        <div class="important-news-original"></div>
      `;
      const original = source.cloneNode(true);
      original.classList.add('important-news-clone');
      hero.querySelector('.important-news-original').appendChild(original);
      content.insertBefore(hero, content.firstChild);
    } finally {
      enhancingNews = false;
    }
  }

  function render() {
    renderClock();
    renderEntryCountdown();
    enhanceImportantNews();
  }

  render();
  window.setInterval(render, 1000);
  window.setInterval(checkAlphaDirection, 30000);

  const content = document.getElementById('news-content');
  if (content && 'MutationObserver' in window) {
    let observerTimer = null;
    const observer = new MutationObserver(() => {
      if (enhancingNews) return;
      window.clearTimeout(observerTimer);
      observerTimer = window.setTimeout(() => {
        enhanceImportantNews();
        checkAlphaDirection();
      }, 20);
    });
    observer.observe(content, { childList: true, subtree: true });
  }
})();

/* Persistent browser-side Last Known Good News + Direction.
   This is intentionally in the existing loaded JS so no template change is required. */
(() => {
  const content = document.getElementById('news-content');
  if (!content) return;
  const NEWS_KEY = 'mmc_news_lkg_v3:';
  const DIR_KEY = 'mmc_news_direction_v3:';
  const read = (k) => { try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch (_) { return null; } };
  const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} };
  const currentKey = () => `${NEWS_KEY}${document.getElementById('mode')?.value || 'real'}:${document.getElementById('pair')?.value || ''}`;
  const currentDirKey = () => `${DIR_KEY}${document.getElementById('mode')?.value || 'real'}:${document.getElementById('pair')?.value || ''}`;
  const findSource = () => content.querySelector(':scope > .news-alert.news-impact-high, :scope > .news-list li.news-impact-high, :scope > .news-alert.news-impact-medium, :scope > .news-list li.news-impact-medium');
  const timeOf = (node) => { const m = (node?.textContent || '').match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/); return m ? m[0] : ''; };

  function saveNews() {
    const source = findSource();
    if (!source || source.dataset.mmcLkg === '1') return;
    const t = timeOf(source);
    if (!t) return;
    write(currentKey(), {html: source.outerHTML, eventTime: t, savedAt: Date.now()});
  }

  function restoreNews() {
    if (findSource()) return;
    const snap = read(currentKey());
    if (!snap?.html || !snap.eventTime) return;
    const eventMs = Date.parse(snap.eventTime);
    if (!Number.isFinite(eventMs) || eventMs < Date.now() - 5 * 60 * 1000) return;
    const holder = document.createElement('div');
    holder.innerHTML = snap.html;
    const node = holder.firstElementChild;
    if (!node) return;
    node.dataset.mmcLkg = '1';
    content.innerHTML = '';
    content.appendChild(node);
    updateCountdown(node, eventMs);
  }

  function updateCountdown(node, eventMs) {
    const count = node?.querySelector('.news-count');
    if (!count) return;
    const seconds = Math.max(0, Math.ceil((eventMs - Date.now()) / 1000));
    count.textContent = seconds <= 0 ? '⏱ নিউজের নির্ধারিত সময় পার হয়েছে' : `⏱ আর ${Math.floor(seconds / 60)} মিনিট ${seconds % 60} সেকেন্ড`;
  }

  function saveDirection() {
    const hero = document.getElementById('important-news-hero');
    const node = hero?.querySelector('.important-news-direction');
    const source = findSource();
    if (!node || !source) return;
    const t = timeOf(source);
    const match = (node.textContent || '').match(/\b(UP|DOWN)\b/i);
    if (!t || !match) return;
    write(currentDirKey(), {eventTime: t, direction: match[1].toUpperCase(), savedAt: Date.now()});
  }

  function restoreDirection() {
    const saved = read(currentDirKey());
    const source = findSource();
    if (!saved?.eventTime || !saved.direction || !source || timeOf(source) !== saved.eventTime) return;
    const text = saved.direction === 'UP' ? '⬆ UP — উপরে' : '⬇ DOWN — নিচে';
    document.querySelectorAll('#important-news-hero .important-news-direction, #important-news-status .ins-direction').forEach((node) => {
      node.className = node.className.replace(/\b(up|down|wait)\b/gi, '').trim() + ` ${saved.direction.toLowerCase()}`;
      node.textContent = text;
    });
  }

  function tick() {
    saveNews();
    restoreNews();
    const source = findSource();
    if (source) {
      const ms = Date.parse(timeOf(source));
      if (Number.isFinite(ms)) updateCountdown(source, ms);
    }
    restoreDirection();
  }

  tick();
  window.setInterval(tick, 1000);
  if ('MutationObserver' in window) {
    const observer = new MutationObserver(() => window.setTimeout(tick, 30));
    observer.observe(content, {childList: true, subtree: true});
  }
  document.getElementById('pair')?.addEventListener('change', () => window.setTimeout(tick, 100));
  document.getElementById('mode')?.addEventListener('change', () => window.setTimeout(tick, 100));
})();
