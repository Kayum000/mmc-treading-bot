(() => {
  'use strict';

  // Prevent the important-news MutationObserver from hammering /news-direction.
  // Only one Alpha Vantage request is allowed per event/pair in a 30s window.
  const originalFetch = window.fetch.bind(window);
  let lastDirectionRequestAt = 0;
  let lastDirectionRequestKey = '';
  let inFlight = null;

  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : (input?.url || '');
    if (!url.includes('/news-direction')) return originalFetch(input, init);

    const now = Date.now();
    const pair = document.getElementById('pair')?.value || '';
    const key = `${url}|${pair}`;

    if (inFlight) return inFlight;
    if (key === lastDirectionRequestKey && now - lastDirectionRequestAt < 30000) {
      return Promise.resolve(new Response(JSON.stringify({ok:true, needed:false, throttled:true}), {
        status: 200,
        headers: {'Content-Type':'application/json'}
      }));
    }

    lastDirectionRequestKey = key;
    lastDirectionRequestAt = now;
    inFlight = originalFetch(input, init).finally(() => { inFlight = null; });
    return inFlight;
  };

  // Keep News Events scrolling stable while the 30-second calendar refresh runs.
  const content = document.getElementById('news-content');
  if (!content) return;

  let savedScrollTop = 0;
  let restoreTimer = null;
  content.addEventListener('scroll', () => { savedScrollTop = content.scrollTop; }, {passive:true});

  const observer = new MutationObserver(() => {
    clearTimeout(restoreTimer);
    restoreTimer = setTimeout(() => {
      if (Math.abs(content.scrollTop - savedScrollTop) > 1) content.scrollTop = savedScrollTop;
    }, 0);
  });
  observer.observe(content, {childList:true, subtree:true});
})();
