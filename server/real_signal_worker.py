"""24/7 Real Market signal loop for the self-hosted MMC server.

OTC is intentionally excluded. The worker only calls the Real Market signal
engine for pairs configured in REAL_SIGNAL_PAIRS.
"""
from __future__ import annotations

import os
import time

from signals.get_signal import get_signal

PAIRS = [p.strip().upper() for p in os.getenv("REAL_SIGNAL_PAIRS", "AUD/CAD").split(",") if p.strip()]
INTERVAL = max(15, int(os.getenv("REAL_SIGNAL_INTERVAL_SECONDS", "60")))


def log(message: str) -> None:
    print(f"[MMC Real Signal Worker] {message}", flush=True)


def run() -> None:
    log(f"started; pairs={PAIRS}; interval={INTERVAL}s")
    while True:
        for pair in PAIRS:
            try:
                result = get_signal(pair, "real", automatic=True)
                log(f"{pair}: {result.get('signal')} confidence={result.get('confidence')}")
            except Exception as exc:
                log(f"{pair}: signal error: {exc}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    run()
