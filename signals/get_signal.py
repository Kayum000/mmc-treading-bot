"""Live 1-minute MMC signal generation for the selected Real or Crypto market."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import threading

import pandas as pd

from data.twelve_data_forex import fetch_forex_candles
from data.binance_crypto import fetch_crypto_candles
from strategy.signal import generate_1m_signal, Signal
from strategy.reentry_guard import check_reentry_guard
from performance import settle_pending, loss_lock_reason

_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _next_candle_boundary_utc(now_utc: datetime, seconds: int = 60) -> datetime:
    epoch = int(now_utc.timestamp())
    next_epoch = ((epoch // seconds) + 1) * seconds
    return datetime.fromtimestamp(next_epoch, tz=timezone.utc)


def _period_start(now_utc: datetime, seconds: int) -> int:
    return (int(now_utc.timestamp()) // seconds) * seconds


def _load_1m_frame(pair: str, market_mode: str, now_utc: datetime, automatic: bool):
    """Load the selected market's 1m candles, refreshing at most once/minute in auto mode."""
    key = (market_mode, pair)
    current_period = _period_start(now_utc, 60)

    if automatic:
        with _CACHE_LOCK:
            cached = _CACHE.get(key, {})
            frame = cached.get("entry_frame")
            period = cached.get("entry_period")
        if frame is not None and period == current_period:
            return frame

    if market_mode == "crypto":
        frame = fetch_crypto_candles(pair.replace("/", ""), "1m")
    else:
        frame = fetch_forex_candles(pair, "1min")

    if automatic:
        with _CACHE_LOCK:
            _CACHE[key] = {"entry_frame": frame, "entry_period": current_period}
    return frame


def get_signal(pair: str, market_mode: str = "real", automatic: bool = False) -> dict:
    """Generate a pure 1m MMC signal for only the selected market.

    The 30m/15m/5m MTF engine is intentionally not called here. The latest
    closed 1m candle is analyzed and any valid signal is an entry for the
    next 1m candle, never the candle currently forming.

    After a confirmed LOSS, the selected market is locked. The lock is removed
    only after a later NO_TRADE observation, so a new BUY/SELL must come from a
    genuinely fresh MMC setup rather than the losing setup continuing.
    """
    pair = pair.strip().upper()
    market_mode = market_mode.strip().lower()
    if market_mode not in {"real", "crypto"}:
        raise ValueError("Unsupported market mode")
    if not pair:
        raise ValueError("No market selected")

    requested_pair = pair
    signal_at_utc = datetime.now(timezone.utc)

    # Resolve any due previous entry before deciding whether this market remains
    # locked. If the database is unavailable, the existing live signal path must
    # continue working normally.
    try:
        settle_pending()
    except Exception:
        pass

    entry_frame = _load_1m_frame(requested_pair, market_mode, signal_at_utc, automatic)
    result = generate_1m_signal(entry_frame)

    # LOSS lock is market/pair-wide: while locked, no BUY/SELL is allowed. A
    # NO_TRADE observation clears the lock; that observation itself remains
    # NO_TRADE. The next fresh valid MMC setup can then signal.
    loss_reason = loss_lock_reason(market_mode, requested_pair, result.action)
    if loss_reason and result.action in {"BUY", "SELL"}:
        result = Signal("NO_TRADE", result.buy_score, result.sell_score, loss_reason)

    # Prevent repeated BUY/SELL entries while the same strong support/resistance
    # level is still active. The guard is deliberately outside the MMC engine:
    # if PostgreSQL is unavailable it fails open and the original signal path is
    # preserved.
    if result.action in {"BUY", "SELL"}:
        block_reason = check_reentry_guard(entry_frame, market_mode, requested_pair, result.action)
        if block_reason:
            result = Signal("NO_TRADE", result.buy_score, result.sell_score, block_reason)

    # The trade is always for the next 1-minute candle.
    next_candle_utc = _next_candle_boundary_utc(signal_at_utc, 60)

    entry_price = None
    candle_time = None
    if entry_frame is not None and not entry_frame.empty:
        row = entry_frame.iloc[-1]
        entry_price = float(row["close"])
        candle_time_utc = pd_timestamp_to_utc(row["timestamp"])
        candle_time = candle_time_utc.isoformat(timespec="seconds")

    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    entry_bd = next_candle_utc.astimezone(timezone(timedelta(hours=6)))
    entry_time_text = entry_bd.strftime("%d %b %Y, %H:%M:%S")
    reason_text = (
        f"{result.reason} Entry is for the NEXT 1-MINUTE CANDLE at "
        f"{entry_time_text} Bangladesh time ({next_candle_utc.strftime('%H:%M:%S')} UTC), "
        "not the currently running candle."
    )

    return {
        "pair": requested_pair,
        "requested_pair": requested_pair,
        "market_mode": market_mode,
        "source": "Binance" if market_mode == "crypto" else "Twelve Data",
        "signal": result.action,
        "buy_score": result.buy_score,
        "sell_score": result.sell_score,
        "reason": reason_text,
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": candle_time,
        "analysis_candle_time_utc": candle_time,
        "entry_price": entry_price,
        "entry_price_type": "last_closed_1m_close_reference",
        "entry_time_utc": next_candle_utc.isoformat(timespec="seconds"),
        "entry_time_bd": entry_time_text,
        "entry_delay_seconds": 0,
        "timeframe": "1m pure MMC entry",
        "entry_timeframe": "1m",
        "automatic": automatic,
    }


def pd_timestamp_to_utc(value) -> datetime:
    """Convert a candle timestamp to an aware UTC datetime."""
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
