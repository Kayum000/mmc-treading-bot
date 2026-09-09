(() => {
  let audioContext = null;
  let lastSignalKey = '';

  function ensureAudio() {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return null;
    if (!audioContext) audioContext = new AudioCtx();
    if (audioContext.state === 'suspended') audioContext.resume().catch(() => {});
    return audioContext;
  }

  function tone(ctx, frequency, start, duration, volume) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(volume, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    osc.connect(gain).connect(ctx.destination);
    osc.start(start);
    osc.stop(start + duration + 0.03);
  }

  function playSignalSound(signal) {
    const ctx = ensureAudio();
    if (!ctx) return;
    const now = ctx.currentTime + 0.03;
    if (signal === 'BUY') {
      tone(ctx, 880, now, 0.16, 0.18);
      tone(ctx, 1175, now + 0.20, 0.20, 0.18);
    } else if (signal === 'SELL') {
      tone(ctx, 740, now, 0.16, 0.18);
      tone(ctx, 587, now + 0.20, 0.20, 0.18);
      tone(ctx, 440, now + 0.40, 0.24, 0.16);
    }
  }

  function showBrowserNotification(signal, pair) {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'granted') {
      try {
        new Notification(`MMC ${signal}`, {
          body: `${pair || 'Market'} — ${signal} signal` 
        });
      } catch (_) {}
    }
  }

  window.enableSignalAudio = function () {
    ensureAudio();
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {});
    }
  };

  window.alertForSignal = function (result) {
    if (!result || !result.signal) return;
    const signal = String(result.signal).toUpperCase();
    if (signal !== 'BUY' && signal !== 'SELL') return;

    const key = `${result.pair || ''}|${signal}|${result.entry_time_utc || ''}`;
    if (key === lastSignalKey) return;
    lastSignalKey = key;

    playSignalSound(signal);
    showBrowserNotification(signal, result.pair);

    if (window.AndroidSignalAlert && typeof window.AndroidSignalAlert.notifySignal === 'function') {
      try {
        window.AndroidSignalAlert.notifySignal(signal, String(result.pair || 'MMC Live Signal'));
      } catch (_) {}
    }
  };

  document.addEventListener('click', () => window.enableSignalAudio(), { once: true });
})();
