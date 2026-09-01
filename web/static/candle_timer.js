(() => {
  const timer = document.querySelector('[data-candle-timer]');
  if (!timer) return;

  const intervalSeconds = Number(timer.dataset.intervalSeconds || 60);
  if (!Number.isFinite(intervalSeconds) || intervalSeconds <= 0) return;

  const pad = (value) => String(value).padStart(2, '0');

  function render() {
    // Use epoch time so the countdown follows the user's actual clock and
    // rolls exactly on the market candle boundary, without touching signals.
    const nowMs = Date.now();
    const elapsed = Math.floor(nowMs / 1000) % intervalSeconds;
    const remaining = intervalSeconds - elapsed;
    const minutes = Math.floor(remaining / 60);
    const seconds = remaining % 60;

    timer.textContent = `${pad(minutes)}:${pad(seconds)}`;
    timer.setAttribute('aria-label', `Current candle closes in ${minutes} minutes ${seconds} seconds`);
  }

  render();
  window.setInterval(render, 250);
})();
