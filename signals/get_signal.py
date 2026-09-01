"""On-demand live Forex signal: fetch only the selected pair when requested."""
from __future__ import annotations

from data.twelve_data_forex import fetch_forex_multi_timeframe
from data.live_signal import build_signal


def get_signal(pair: str) -> dict:
    """Fetch fresh 1m/5m/15m data for one pair and return one analysis result."""
    pair = pair.strip().upper()
    frames = fetch_forex_multi_timeframe(pair)
    result = build_signal(frames)
    return {
        "pair": pair,
        "signal": result.action,
        "buy_score": result.buy_score,
        "sell_score": result.sell_score,
        "reason": result.reason,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Get one fresh live Forex signal")
    parser.add_argument("pair", help="Selected pair, e.g. EUR/USD")
    args = parser.parse_args()
    print(get_signal(args.pair))
