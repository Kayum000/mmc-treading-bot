(() => {
  'use strict';

  // AUTO SIGNAL is intentionally one-shot: once a real BUY/SELL is produced,
  // stop scheduling the same auto stream until the user enables it again.
  const originalFetch = window.fetch.bind(window);

  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    try {
      const requestUrl = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
      if (!String(requestUrl).includes('/auto-signal')) return response;

      const payload = await response.clone().json();
      const signal = String(payload?.result?.signal || '').toUpperCase();
      if (response.ok && payload?.ok && (signal === 'BUY' || signal === 'SELL')) {
        const toggle = document.getElementById('auto-signal');
        const status = document.getElementById('auto-status');
        if (toggle) toggle.checked = false;
        try { localStorage.setItem('mmc_auto_signal_enabled', '0'); } catch (_) {}
        if (status) status.textContent = `একটি ${signal} signal তৈরি হয়েছে — AUTO SIGNAL বন্ধ`;
      }
    } catch (_) {
      // Never interfere with the original response or signal flow.
    }
    return response;
  };
})();
