"""On-demand live MMC signal for the selected Real or Crypto market."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import time

from data.twelve_data_forex import fetch_forex_multi_timeframe
from data.binance_crypto import fetch_crypto_multi_timeframe
from data.live_signal import build_signal

ENTRY_LEAD_SECONDS = 30


def _next_candle_boundary_utc(now_utc: datetime) -> datetime:
    epoch = int(now_utc.timestamp())
    next_epoch = ((epoch // 60) + 1) * 60
    return datetime.fromtimestamp(next_epoch, tz=timezone.utc)


def get_signal(pair: str, market_mode: str = "real") -> dict:
    # Keep the user's selected market as the single source of truth.
    pair = pair.strip().upper()
    market_mode = market_mode.strip().lower()
    if market_mode not in {"real", "crypto"}:
        raise ValueError("Unsupported market mode")

    requested_pair = pair
    requested_at_utc = datetime.now(timezone.utc)
    next_candle_utc = _next_candle_boundary_utc(requested_at_utc)
    signal_at_utc = next_candle_utc - timedelta(seconds=ENTRY_LEAD_SECONDS)
    wait_seconds = (signal_at_utc - requested_at_utc).total_seconds()
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    signal_at_utc = datetime.now(timezone.utc)
    next_candle_utc = _next_candle_boundary_utc(signal_at_utc)

    if market_mode == "crypto":
        symbol = requested_pair.replace("/", "")
        frames = fetch_crypto_multi_timeframe(symbol)
        source = "Binance"
    else:
        frames = fetch_forex_multi_timeframe(requested_pair)
        source = "Twelve Data"

    result = build_signal(frames)

    latest = frames.get("1m")
    entry_price = None
    candle_time = None
    if latest is not None and not latest.empty:
        row = latest.iloc[-1]
        entry_price = float(row["close"])
        candle_time = str(latest.index[-1])

    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    entry_bd = next_candle_utc.astimezone(timezone(timedelta(hours=6)))

    return {
        # Always display the exact market selected before GET SIGNAL.
        "pair": requested_pair,
        "requested_pair": requested_pair,
        "market_mode": market_mode,
        "source": source,
        "signal": result.action,
        "buy_score": result.buy_score,
        "sell_score": result.sell_score,
        "reason": result.reason,
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": candle_time,
        "entry_price": entry_price,
        "entry_time_utc": next_candle_utc.isoformat(timespec="seconds"),
        "entry_time_bd": entry_bd.strftime("%d %b %Y, %H:%M:%S"),
        "entry_delay_seconds": ENTRY_LEAD_SECONDS,
        "timeframe": "1m entry / 5m + 15m confirmation",
    }
