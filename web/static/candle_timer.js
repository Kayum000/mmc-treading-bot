(() => {
  const bdClock = document.querySelector('[data-bd-clock]');
  const pad = (value) => String(value).padStart(2, '0');
  let enhancingNews = false;
  let directionRequestInFlight = false;
  let lastDirectionKey = '';

  function renderClock() {
    if (!bdClock) return;
    const now = new Date();
    const bd = new Date(now.getTime() + (6 * 60 * 60 * 1000));
    const hours = bd.getUTCHours();
    const minutes = bd.getUTCMinutes();
    const seconds = bd.getUTCSeconds();
    bdClock.textContent = `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
  }

  function renderEntryCountdown() {
    const entryTimer = document.querySelector('[data-entry-timer]');
    if (!entryTimer) return;
    const entryAt = Date.parse(entryTimer.dataset.entryAt || '');
    if (!Number.isFinite(entryAt)) return;
    const remainingSeconds = Math.max(0, Math.ceil((entryAt - Date.now()) / 1000));
    const minutes = Math.floor(remainingSeconds / 60);
    const seconds = remainingSeconds % 60;
    entryTimer.textContent = remainingSeconds > 0
      ? `${pad(minutes)}:${pad(seconds)}`
      : '00:00 — ENTRY NOW';
    entryTimer.setAttribute('aria-label', remainingSeconds > 0
      ? `Entry starts in ${minutes} minutes ${seconds} seconds`
      : 'Entry time reached');
  }

  function injectNewsStyles() {
    if (document.getElementById('important-news-styles')) return;
    const style = document.createElement('style');
    style.id = 'important-news-styles';
    style.textContent = `
      #important-news-hero{margin:0 0 14px;padding:16px;border:3px solid #f59e0b;border-radius:14px;background:#fff8dc;box-shadow:0 4px 14px rgba(0,0,0,.08)}
      #important-news-hero .important-news-heading{font-size:24px;font-weight:900;margin-bottom:10px;color:#9a5b00}
      #important-news-hero .important-news-title{font-size:22px;font-weight:900;line-height:1.35;margin:7px 0}
      #important-news-hero .important-news-time{font-size:19px;font-weight:900;line-height:1.4;margin:9px 0;padding:9px 10px;border-radius:9px;background:#fff;border:1px solid #f3c66b}
      #important-news-hero .important-news-count{font-size:19px;font-weight:900;margin:7px 0}
      #important-news-hero .important-news-direction{display:flex;align-items:center;justify-content:center;min-height:62px;margin:11px 0;padding:8px;border-radius:11px;font-size:32px;font-weight:1000;letter-spacing:1px;border:2px solid #cbd5e1;background:#f8fafc}
      #important-news-hero .important-news-direction.up{color:#15803d;border-color:#86efac;background:#f0fdf4}
      #important-news-hero .important-news-direction.down{color:#dc2626;border-color:#fca5a5;background:#fef2f2}
      #important-news-hero .important-news-direction.wait{color:#92400e;border-color:#fcd34d;background:#fffbeb}
      #important-news-hero .important-news-source{font-size:12px;color:#64748b;margin-top:8px}
      #important-news-hero .important-news-original{margin-top:8px}
      #important-news-hero .important-news-original .news-pairs{font-size:15px}
      #important-news-hero .important-news-original .news-prediction{font-size:14px}
      #important-news-status{margin:12px 0 4px;padding:13px;border:2px solid #f59e0b;border-radius:11px;background:#fff8dc}
      #important-news-status .ins-heading{font-size:19px;font-weight:900;color:#9a5b00;margin-bottom:7px}
      #important-news-status .ins-title{font-size:17px;font-weight:900;line-height:1.35;margin-bottom:7px}
      #important-news-status .ins-time{font-size:15px;font-weight:900;line-height:1.5}
      #important-news-status .ins-count{font-size:16px;font-weight:900;margin-top:5px}
      #important-news-status .ins-direction{font-size:25px;font-weight:1000;text-align:center;margin-top:8px;padding:7px;border-radius:9px;border:2px solid #cbd5e1;background:#fff}
      #important-news-status .ins-direction.up{color:#15803d;border-color:#86efac;background:#f0fdf4}
      #important-news-status .ins-direction.down{color:#dc2626;border-color:#fca5a5;background:#fef2f2}
      #important-news-status .ins-direction.wait{color:#92400e;border-color:#fcd34d;background:#fffbeb}
      #alpha-news-direction-status{margin:10px 0 4px;padding:13px;border:2px solid #60a5fa;border-radius:11px;background:#eff6ff}
      #alpha-news-direction-status .and-heading{font-size:18px;font-weight:900;color:#1d4ed8;margin-bottom:7px}
      #alpha-news-direction-status .and-direction{font-size:27px;font-weight:1000;text-align:center;margin:7px 0;padding:8px;border-radius:9px;background:#fff;border:2px solid #bfdbfe}
      #alpha-news-direction-status .and-direction.up{color:#15803d;border-color:#86efac;background:#f0fdf4}
      #alpha-news-direction-status .and-direction.down{color:#dc2626;border-color:#fca5a5;background:#fef2f2}
      #alpha-news-direction-status .and-direction.wait{color:#92400e;border-color:#fcd34d;background:#fffbeb}
      #alpha-news-direction-status .and-meta{font-size:13px;line-height:1.5;color:#334155}
      @media(max-width:600px){#important-news-hero{padding:13px}#important-news-hero .important-news-heading{font-size:21px}#important-news-hero .important-news-title{font-size:19px}#important-news-hero .important-news-time{font-size:17px}#important-news-hero .important-news-direction{font-size:28px}#important-news-status .ins-heading{font-size:18px}#important-news-status .ins-direction{font-size:23px}#alpha-news-direction-status .and-direction{font-size:24px}}
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
    return String(value ?? '').replace(/[&<>\"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function getImportantSource(content) {
    return content?.querySelector(
      ':scope > .news-alert.news-impact-high, :scope > .news-list li.news-impact-high, :scope > .news-alert.news-impact-medium, :scope > .news-list li.news-impact-medium'
    );
  }

  function updateMarketStatusImportantNews(source) {
    const panel = document.getElementById('market-status-panel');
    if (!panel) return;
    let box = document.getElementById('important-news-status');
    if (!source) {
      if (box) box.remove();
      return;
    }
    const eventTime = extractEventTime(source);
    const bdTime = formatBangladeshTime(eventTime);
    const title = extractTitle(source);
    const countdown = source.querySelector('.news-count')?.textContent?.trim() || '';
    if (!box) {
      box = document.createElement('div');
      box.id = 'important-news-status';
      const note = panel.querySelector('.status-note');
      if (note) panel.insertBefore(box, note);
      else panel.appendChild(box);
    }
    box.innerHTML = `
      <div class="ins-heading">🚨 গুরুত্বপূর্ণ নিউজ</div>
      <div class="ins-title">${escapeText(title)}</div>
      <div class="ins-time">🕒 REAL MARKET TIME (UTC): ${escapeText(eventTime)}</div>
      ${bdTime ? `<div class="ins-time">🇧🇩 বাংলাদেশ সময়: ${escapeText(bdTime)}</div>` : ''}
      ${countdown ? `<div class="ins-count">⏱ ${escapeText(countdown)}</div>` : ''}
      <div class="ins-direction wait">⏳ Direction বিশ্লেষণ দরকার হলে Alpha Vantage কল হবে</div>
    `;
  }

  function renderAlphaDirection(data) {
    const panel = document.getElementById('market-status-panel');
    if (!panel) return;
    let box = document.getElementById('alpha-news-direction-status');
    if (!data?.needed || !data?.event) {
      if (box) box.remove();
      return;
    }
    const event = data.event;
    const direction = String(event.direction || 'WAIT').toUpperCase();
    const sentiment = event.news_sentiment || {};
    if (!box) {
      box = document.createElement('div');
      box.id = 'alpha-news-direction-status';
      const note = panel.querySelector('.status-note');
      if (note) panel.insertBefore(box, note);
      else panel.appendChild(box);
    }
    box.innerHTML = `
      <div class="and-heading">🧠 News Direction — Alpha Vantage</div>
      <div class="and-direction ${direction.toLowerCase()}">${direction === 'UP' ? '⬆ UP — উপরে' : direction === 'DOWN' ? '⬇ DOWN — নিচে' : '⏸ WAIT — দিক নিশ্চিত নয়'}</div>
      <div class="and-meta">নিউজ: ${escapeText(event.title_bn || event.title || '')}<br>সময়: ${escapeText(event.event_time_utc || '')} UTC<br>Sentiment: ${escapeText(sentiment.label_bn || 'তথ্য নেই')} | Score: ${escapeText(sentiment.score ?? '—')} | Articles: ${escapeText(sentiment.articles ?? 0)}<br>${escapeText(event.direction_basis_bn || 'Alpha Vantage sentiment ভিত্তিক সম্ভাব্য bias।')}<br><strong>এটি নিশ্চিত BUY/SELL prediction নয়।</strong></div>
    `;
  }

  async function checkAlphaDirection() {
    const content = document.getElementById('news-content');
    const source = getImportantSource(content);
    if (!source || !source.classList.contains('news-impact-high') && !source.matches('.news-list li.news-impact-high')) return;
    const eventTime = extractEventTime(source);
    const key = `${eventTime}|${document.getElementById('pair')?.value || ''}`;
    if (directionRequestInFlight || key === lastDirectionKey) return;
    directionRequestInFlight = true;
    try {
      const response = await fetch('/news-direction', {method:'GET', cache:'no-store', headers:{'Accept':'application/json'}});
      const data = await response.json();
      if (data?.needed) {
        lastDirectionKey = key;
        renderAlphaDirection(data);
      } else {
        renderAlphaDirection(null);
      }
    } catch (e) {
      renderAlphaDirection(null);
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
    updateMarketStatusImportantNews(source);
    const oldHero = document.getElementById('important-news-hero');
    if (!source) {
      if (oldHero) oldHero.remove();
      renderAlphaDirection(null);
      return;
    }

    const eventTime = extractEventTime(source);
    const bdTime = formatBangladeshTime(eventTime);
    const title = extractTitle(source);
    const countdown = source.querySelector('.news-count')?.textContent?.trim() || '';

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
        <div class="important-news-direction wait">⏳ Direction Market Status-এ প্রয়োজন হলে বিশ্লেষণ হবে</div>
        <div class="important-news-source">News Events-এর calendar data আলাদা রাখা হয়েছে; Alpha Vantage শুধু direction দরকার হলে ব্যবহার হবে।</div>
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
