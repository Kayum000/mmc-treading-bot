"""On-demand live Forex signal for the selected pair."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from data.twelve_data_forex import fetch_forex_multi_timeframe
from data.live_signal import build_signal


def get_signal(pair: str) -> dict:
    pair = pair.strip().upper()
    frames = fetch_forex_multi_timeframe(pair)
    result = build_signal(frames)

    latest = frames.get("1m")
    entry_price = None
    candle_time = None
    if latest is not None and not latest.empty:
        row = latest.iloc[-1]
        entry_price = float(row["close"])
        candle_time = str(latest.index[-1])

    now_utc = datetime.now(timezone.utc)
    now_bd = now_utc.astimezone(timezone(timedelta(hours=6)))

    return {
        "pair": pair,
        "signal": result.action,
        "buy_score": result.buy_score,
        "sell_score": result.sell_score,
        "reason": result.reason,
        "signal_time_utc": now_utc.isoformat(timespec="seconds"),
        "signal_time_bd": now_bd.strftime("%d %b %Y, %I:%M:%S %p"),
        "candle_time": candle_time,
        "entry_price": entry_price,
        "timeframe": "1m entry / 5m + 15m confirmation",
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Get one fresh live Forex signal")
    parser.add_argument("pair")
    args = parser.parse_args()
    print(get_signal(args.pair))
