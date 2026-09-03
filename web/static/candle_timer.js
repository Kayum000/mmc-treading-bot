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

  function render() {
    renderClock();
    renderEntryCountdown();
  }

  render();
  window.setInterval(render, 250);
})();
