"""24/7 Real Market signal loop for the self-hosted MMC server.

OTC is intentionally excluded. The worker only calls the Real Market signal
engine for pairs configured in REAL_SIGNAL_PAIRS.
"""
from __future__ import annotations

import os
import time

from signals.get_signal import get_signal

PAIRS = [p.strip().upper() for p in os.getenv("REAL_SIGNAL_PAIRS", "AUD/CAD").split(",") if p.strip()]

def seconds_to_signal_window() -> float:
    # Run AUTO just after the minute boundary. The signal engine analyzes
    # the just-closed candle and announces the upcoming 1-minute entry candle,
    # giving roughly one minute of lead time.
    now = time.time()
    return max(0.05, 1.0 - (now % 60.0))


def log(message: str) -> None:
    print(f"[MMC Real Signal Worker] {message}", flush=True)


def run() -> None:
    log(f"started; pairs={PAIRS}; synchronized to 1-minute boundaries")
    while True:
        # Run just after each minute boundary so Real AUTO uses the same
        # next-candle timing as the dashboard AUTO/Get Signal flow.
        time.sleep(seconds_to_signal_window())
        for pair in PAIRS:
            try:
                result = get_signal(pair, "real", automatic=True)
                log(f"{pair}: {result.get('signal')} confidence={result.get('confidence')} entry={result.get('entry_time_utc')}")
            except Exception as exc:
                log(f"{pair}: signal error: {exc}")


if __name__ == "__main__":
    run()
