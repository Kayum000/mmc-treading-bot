(() => {
  'use strict';

  // Stabilize dashboard polling: keep /news-direction and GET /performance
  // from generating repeated requests when the UI or MutationObservers refresh.
  const originalFetch = window.fetch.bind(window);
  let lastDirectionRequestAt = 0;
  let lastDirectionRequestKey = '';
  let directionInFlight = null;
  let performanceCache = null;
  let performanceInFlight = null;

  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : (input?.url || '');
    const method = String(init?.method || (typeof input !== 'string' && input?.method) || 'GET').toUpperCase();
    const now = Date.now();

    // Only throttle GET. POST /performance is the Clear History action and
    // must always reach the server.
    if (url.includes('/performance') && method === 'GET') {
      const mode = document.getElementById('mode')?.value || 'real';
      const pair = document.getElementById('pair')?.value || '';
      const key = `${url}|${mode}|${pair}`;
      if (performanceCache && performanceCache.key === key && now - performanceCache.at < 30000) {
        return Promise.resolve(new Response(JSON.stringify(performanceCache.data), {
          status: 200,
          headers: {'Content-Type':'application/json'}
        }));
      }
      if (performanceInFlight && performanceCache?.key === key) return performanceInFlight;
      performanceInFlight = originalFetch(input, init).then(async response => {
        try {
          const data = await response.clone().json();
          performanceCache = {key, at: Date.now(), data};
        } catch (_) {}
        return response;
      }).finally(() => { performanceInFlight = null; });
      return performanceInFlight;
    }

    if (!url.includes('/news-direction') || method !== 'GET') return originalFetch(input, init);

    const pair = document.getElementById('pair')?.value || '';
    const key = `${url}|${pair}`;
    if (directionInFlight) return directionInFlight;
    if (key === lastDirectionRequestKey && now - lastDirectionRequestAt < 30000) {
      return Promise.resolve(new Response(JSON.stringify({ok:true, needed:false, throttled:true}), {
        status: 200,
        headers: {'Content-Type':'application/json'}
      }));
    }

    lastDirectionRequestKey = key;
    lastDirectionRequestAt = now;
    directionInFlight = originalFetch(input, init).finally(() => { directionInFlight = null; });
    return directionInFlight;
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
