(() => {
  const bdClock = document.querySelector('[data-bd-clock]');
  const pad = (value) => String(value).padStart(2, '0');

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

    entryTimer.setAttribute(
      'aria-label',
      remainingSeconds > 0
        ? `Entry starts in ${minutes} minutes ${seconds} seconds`
        : 'Entry time reached'
    );
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
      .news-important-label{font-size:14px;font-weight:900;color:#9a5b00;margin-bottom:5px}
      @media(max-width:600px){#important-news-hero{padding:13px}#important-news-hero .important-news-heading{font-size:21px}#important-news-hero .important-news-title{font-size:19px}#important-news-hero .important-news-time{font-size:17px}#important-news-hero .important-news-direction{font-size:28px}}
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
    const strong = node?.querySelector('strong');
    if (strong) {
      let title = strong.textContent.trim().replace(/^🚨\s*/, '');
      title = title.replace(/^[^—]+—\s*/, '');
      if (title) return title;
    }
    return 'গুরুত্বপূর্ণ নির্ধারিত নিউজ';
  }

  function formatBangladeshTime(iso) {
    const ms = Date.parse(iso);
    if (!Number.isFinite(ms)) return '';
    const bd = new Date(ms + (6 * 60 * 60 * 1000));
    const y = bd.getUTCFullYear();
    const mo = pad(bd.getUTCMonth() + 1);
    const d = pad(bd.getUTCDate());
    const h = pad(bd.getUTCHours());
    const m = pad(bd.getUTCMinutes());
    const s = pad(bd.getUTCSeconds());
    return `${y}-${mo}-${d} ${h}:${m}:${s} বাংলাদেশ সময়`;
  }

  function escapeText(value) {
    return String(value ?? '').replace(/[&<>\"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function enhanceImportantNews() {
    const content = document.getElementById('news-content');
    if (!content) return;
    injectNewsStyles();

    const oldHero = document.getElementById('important-news-hero');
    if (oldHero) oldHero.remove();

    const candidates = Array.from(content.querySelectorAll(
      '.news-alert.news-impact-high, .news-list li.news-impact-high, .news-alert.news-impact-medium, .news-list li.news-impact-medium'
    ));
    const source = candidates[0];
    if (!source) return;

    const direction = extractDirection(source);
    const eventTime = extractEventTime(source);
    const bdTime = formatBangladeshTime(eventTime);
    const title = extractTitle(source);
    const countdown = source.querySelector('.news-count')?.textContent?.trim() || '';

    const hero = document.createElement('div');
    hero.id = 'important-news-hero';
    hero.setAttribute('role', 'status');
    hero.innerHTML = `
      <div class="important-news-heading">🚨 গুরুত্বপূর্ণ নিউজ</div>
      <div class="important-news-title">${escapeText(title)}</div>
      <div class="important-news-time">🕒 REAL MARKET TIME (UTC): ${escapeText(eventTime)}</div>
      ${bdTime ? `<div class="important-news-time">🇧🇩 বাংলাদেশ সময়: ${escapeText(bdTime)}</div>` : ''}
      ${countdown ? `<div class="important-news-count">⏱ ${escapeText(countdown)}</div>` : ''}
      <div class="important-news-direction ${direction.toLowerCase()}">${direction === 'UP' ? '⬆ UP — উপরে' : direction === 'DOWN' ? '⬇ DOWN — নিচে' : '⏸ WAIT — দিক নিশ্চিত নয়'}</div>
      <div class="important-news-source">দিকটি নিউজ সেন্টিমেন্টভিত্তিক সম্ভাব্য bias; নিশ্চিত BUY/SELL নয়।</div>
      <div class="important-news-original"></div>
    `;
    const original = source.cloneNode(true);
    original.removeAttribute('id');
    original.style.marginTop = '8px';
    hero.querySelector('.important-news-original').appendChild(original);
    content.insertBefore(hero, content.firstChild);
  }

  function render() {
    renderClock();
    renderEntryCountdown();
    enhanceImportantNews();
  }

  render();
  window.setInterval(render, 1000);

  const content = document.getElementById('news-content');
  if (content && 'MutationObserver' in window) {
    const observer = new MutationObserver(() => {
      window.setTimeout(enhanceImportantNews, 0);
    });
    observer.observe(content, { childList: true, subtree: true });
  }
})();
