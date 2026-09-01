"""Signal-only scanner for live Twelve Data Forex candles."""
from __future__ import annotations

import os
import time

from data.twelve_data_forex import fetch_forex_multi_timeframe
from data.live_signal import build_signal

PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "GBP/CHF",
    "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY", "EUR/AUD", "GBP/AUD",
    "AUD/CAD", "NZD/CAD",
]


def scan_once() -> list[dict]:
    results = []
    for pair in PAIRS:
        try:
            frames = fetch_forex_multi_timeframe(pair)
            signal = build_signal(frames)
            results.append({
                "pair": pair,
                "signal": signal.action,
                "buy_score": signal.buy_score,
                "sell_score": signal.sell_score,
                "reason": signal.reason,
            })
        except Exception as exc:
            results.append({"pair": pair, "signal": "ERROR", "reason": str(exc)})
    return results


def run(interval_seconds: int = 60) -> None:
    """Continuously print live signals. Never places an order."""
    while True:
        for row in scan_once():
            print(f"{row['pair']:8} {row['signal']:9} B={row.get('buy_score','-')} S={row.get('sell_score','-')} | {row['reason']}")
        time.sleep(max(10, interval_seconds))


if __name__ == "__main__":
    if not os.getenv("TWELVE_DATA_API_KEY"):
        raise SystemExit("Set TWELVE_DATA_API_KEY before starting the Forex scanner.")
    run()
