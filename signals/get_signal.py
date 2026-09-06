"""Live multi-timeframe MMC signal generation for the selected Real or Crypto market."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import threading

import pandas as pd

from data.twelve_data_forex import fetch_forex_candles
from data.binance_crypto import fetch_crypto_candles
from strategy.signal import generate_signal, Signal
from strategy.reentry_guard import check_reentry_guard
from performance import settle_pending, loss_lock_reason, pending_trade_reason

_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _next_candle_boundary_utc(now_utc: datetime, seconds: int = 60) -> datetime:
    epoch = int(now_utc.timestamp())
    next_epoch = ((epoch // seconds) + 1) * seconds
    return datetime.fromtimestamp(next_epoch, tz=timezone.utc)


def _period_start(now_utc: datetime, seconds: int) -> int:
    return (int(now_utc.timestamp()) // seconds) * seconds


def _fetch_frame(pair: str, market_mode: str, timeframe: str):
    if market_mode == "crypto":
        return fetch_crypto_candles(pair.replace("/", ""), timeframe)
    return fetch_forex_candles(pair, {"30m": "30min", "15m": "15min", "5m": "5min", "1m": "1min"}[timeframe])


def _load_frames(pair: str, market_mode: str, now_utc: datetime, automatic: bool):
    """Load only the selected market and cache each timeframe until its candle period changes."""
    key = (market_mode, pair)
    frames = {}
    periods = {
        "30m": _period_start(now_utc, 1800),
        "15m": _period_start(now_utc, 900),
        "5m": _period_start(now_utc, 300),
        "1m": _period_start(now_utc, 60),
    }

    with _CACHE_LOCK:
        cached = _CACHE.get(key, {}) if automatic else {}

    for tf in ("30m", "15m", "5m", "1m"):
        if automatic and cached.get(tf) is not None and cached.get(f"{tf}_period") == periods[tf]:
            frames[tf] = cached[tf]
        else:
            frames[tf] = _fetch_frame(pair, market_mode, tf)

    if automatic:
        with _CACHE_LOCK:
            _CACHE[key] = {}
            for tf in ("30m", "15m", "5m", "1m"):
                _CACHE[key][tf] = frames[tf]
                _CACHE[key][f"{tf}_period"] = periods[tf]

    return frames


def get_signal(pair: str, market_mode: str = "real", automatic: bool = False) -> dict:
    """Generate one pure-MMC next-1m-candle entry for the selected market.

    The strategy decision is centralized in strategy.signal.generate_signal:
    30m direction -> 15m confirmation -> 5m setup -> 1m final confirmation.
    """
    pair = pair.strip().upper()
    market_mode = market_mode.strip().lower()
    if market_mode not in {"real", "crypto"}:
        raise ValueError("Unsupported market mode")
    if not pair:
        raise ValueError("No market selected")

    requested_pair = pair
    signal_at_utc = datetime.now(timezone.utc)
    next_candle_utc = _next_candle_boundary_utc(signal_at_utc, 60)

    try:
        settle_pending()
    except Exception:
        pass

    pending_reason = pending_trade_reason(market_mode, requested_pair)
    if pending_reason:
        signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
        entry_bd = next_candle_utc.astimezone(timezone(timedelta(hours=6)))
        entry_time_text = entry_bd.strftime("%d %b %Y, %H:%M:%S")
        reason_text = (
            f"{pending_reason} এই কারণে নতুন signal এখন তৈরি করা হয়নি। "
            f"পরবর্তী signal-এর entry সময় হবে {entry_time_text} Bangladesh time "
            f"({next_candle_utc.strftime('%H:%M:%S')} UTC), কিন্তু আগের trade settle না হওয়া পর্যন্ত BUY/SELL বন্ধ।"
        )
        return {
            "pair": requested_pair, "requested_pair": requested_pair, "market_mode": market_mode,
            "source": "Binance" if market_mode == "crypto" else "Twelve Data", "signal": "NO_TRADE",
            "buy_score": 0, "sell_score": 0, "reason": reason_text,
            "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
            "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "candle_time": None,
            "analysis_candle_time_utc": None, "entry_price": None, "entry_price_type": "pending_trade_block",
            "entry_time_utc": next_candle_utc.isoformat(timespec="seconds"), "entry_time_bd": entry_time_text,
            "entry_delay_seconds": 0, "timeframe": "30m + 15m + 5m confirmation / 1m entry",
            "entry_timeframe": "1m", "automatic": automatic,
        }

    frames = _load_frames(requested_pair, market_mode, signal_at_utc, automatic)
    entry_frame = frames["1m"]
    result = generate_signal(frames)

    loss_reason = loss_lock_reason(market_mode, requested_pair, result.action)
    if loss_reason and result.action in {"BUY", "SELL"}:
        result = Signal("NO_TRADE", result.buy_score, result.sell_score, loss_reason)

    if result.action in {"BUY", "SELL"}:
        block_reason = check_reentry_guard(entry_frame, market_mode, requested_pair, result.action)
        if block_reason:
            result = Signal("NO_TRADE", result.buy_score, result.sell_score, block_reason)

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
        "pair": requested_pair, "requested_pair": requested_pair, "market_mode": market_mode,
        "source": "Binance" if market_mode == "crypto" else "Twelve Data", "signal": result.action,
        "buy_score": result.buy_score, "sell_score": result.sell_score, "reason": reason_text,
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "candle_time": candle_time,
        "analysis_candle_time_utc": candle_time, "entry_price": entry_price,
        "entry_price_type": "last_closed_1m_close_reference", "entry_time_utc": next_candle_utc.isoformat(),
        "entry_time_bd": entry_time_text, "entry_delay_seconds": 0,
        "timeframe": "30m + 15m + 5m confirmation / 1m entry", "entry_timeframe": "1m",
        "automatic": automatic,
    }


def pd_timestamp_to_utc(value) -> datetime:
    """Convert a candle timestamp to an aware UTC datetime."""
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
