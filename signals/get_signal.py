"""Live single-timeframe MM-free signal generation for the selected market."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import threading

import pandas as pd

from data.biquote_forex import fetch_forex_candles
from data.binance_crypto import fetch_crypto_candles
from strategy.mmc_advanced import Signal, generate_signal, market_bias, level_for_side
from strategy.reentry_guard import check_reentry_guard
from performance import settle_pending, loss_lock_reason, pending_trade_reason

_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _next_candle_boundary_utc(now_utc: datetime) -> datetime:
    epoch = int(now_utc.timestamp())
    return datetime.fromtimestamp(((epoch // 60) + 1) * 60, tz=timezone.utc)


def _period_start(now_utc: datetime) -> int:
    return (int(now_utc.timestamp()) // 60) * 60


def _fetch_frame(pair: str, market_mode: str):
    if market_mode == "crypto":
        return fetch_crypto_candles(pair.replace("/", ""), "1m")
    return fetch_forex_candles(pair, "1min")


def _closed_1m_frame(frame, now_utc: datetime):
    if frame is None or frame.empty or "timestamp" not in frame.columns:
        return frame
    current_start = pd.Timestamp.fromtimestamp(_period_start(now_utc), tz="UTC")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return frame.loc[timestamps < current_start].copy()


def _load_frame(pair: str, market_mode: str, now_utc: datetime, automatic: bool):
    key = (market_mode, pair)
    period = _period_start(now_utc)
    with _CACHE_LOCK:
        cached = _CACHE.get(key) if automatic else None
    if automatic and cached is not None and cached.get("period") == period:
        return cached["frame"]
    frame = _closed_1m_frame(_fetch_frame(pair, market_mode), now_utc)
    if automatic:
        with _CACHE_LOCK:
            _CACHE[key] = {"period": period, "frame": frame}
    return frame


def _bengali_reason(reason: str) -> str:
    text = str(reason or "").strip()
    replacements = (
        ("BUY", "ক্রয়"), ("SELL", "বিক্রয়"), ("NO_TRADE", "কোনো ট্রেড নয়"),
        ("bias", "বাজারের দিক"), ("edge", "দিকের শক্তি"), ("weak entry edge", "এন্ট্রির শক্তি কম"),
        ("MM-free PA entry", "MMC-বিহীন Price Action Entry"),
        ("MM-free PA", "MMC-বিহীন Price Action"),
        ("insufficient history", "পর্যাপ্ত ইতিহাস নেই"),
        ("pending", "অপেক্ষমাণ"), ("entry", "এন্ট্রি"), ("Candle", "ক্যান্ডেল"),
        ("level", "লেভেল"), ("loss lock", "লস-লক"), ("re-entry", "পুনঃএন্ট্রি"),
    )
    for source, translated in replacements:
        text = text.replace(source, translated)
    return text


def get_signal(pair: str, market_mode: str = "real", automatic: bool = False) -> dict:
    pair = pair.strip().upper()
    market_mode = market_mode.strip().lower()
    if market_mode not in {"real", "crypto"}:
        raise ValueError("Unsupported market mode")
    if not pair:
        raise ValueError("No market selected")

    signal_at_utc = datetime.now(timezone.utc)
    next_candle_utc = _next_candle_boundary_utc(signal_at_utc)
    entry_frame = _load_frame(pair, market_mode, signal_at_utc, automatic)
    try:
        settle_pending({(market_mode, pair): entry_frame})
    except Exception:
        pass

    # Dashboard direction is NEVER blank: it is the current market bias.
    bias = market_bias(entry_frame)

    pending_reason = pending_trade_reason(market_mode, pair)
    if pending_reason:
        signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
        entry_bd = next_candle_utc.astimezone(timezone(timedelta(hours=6)))
        entry_time_text = entry_bd.strftime("%d %b %Y, %H:%M:%S")
        return {
            "pair": pair, "requested_pair": pair, "market_mode": market_mode,
            "source": "Binance" if market_mode == "crypto" else "BiQuote",
            "signal": bias, "market_bias": bias, "entry_signal": "NO_TRADE",
            "buy_score": 0, "sell_score": 0,
            "reason": f"বাজারের দিক: {bias}. {_bengali_reason(pending_reason)} পরবর্তী Candle: {entry_time_text} বাংলাদেশ সময়।",
            "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
            "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
            "candle_time": None, "analysis_candle_time_utc": None,
            "entry_price": None, "entry_price_type": "pending_trade_block",
            "entry_time_utc": next_candle_utc.isoformat(timespec="seconds"),
            "entry_time_bd": entry_time_text,
            "entry_delay_seconds": max(0, int((next_candle_utc - signal_at_utc).total_seconds())),
            "timeframe": "MM-free Price Action / 1m", "entry_timeframe": "1m",
            "automatic": automatic, "mmc_level_type": None, "mmc_level_price": None,
        }

    result = generate_signal(entry_frame)
    level_info = level_for_side(entry_frame, result.action) if result.action in {"BUY", "SELL"} else None
    loss_reason = loss_lock_reason(market_mode, pair, result.action, entry_frame, level_info)
    if loss_reason and result.action in {"BUY", "SELL"}:
        result = Signal("NO_TRADE", result.buy_score, result.sell_score, loss_reason)
        level_info = None
    if result.action in {"BUY", "SELL"}:
        block_reason = check_reentry_guard(entry_frame, market_mode, pair, result.action)
        if block_reason:
            result = Signal("NO_TRADE", result.buy_score, result.sell_score, block_reason)
            level_info = None

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
    reason_text = f"বাজারের দিক: {bias}. {_bengali_reason(result.reason)} পরবর্তী ১-মিনিটের Candle-এ প্রযোজ্য।"
    return {
        "pair": pair, "requested_pair": pair, "market_mode": market_mode,
        "source": "Binance" if market_mode == "crypto" else "BiQuote",
        # Keep `signal` as BUY/SELL for the visible panel; execution logic must use entry_signal.
        "signal": bias, "market_bias": bias, "entry_signal": result.action,
        "buy_score": result.buy_score, "sell_score": result.sell_score,
        "reason": reason_text,
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": candle_time, "analysis_candle_time_utc": candle_time,
        "entry_price": entry_price, "entry_price_type": "last_closed_1m_close_reference",
        "entry_time_utc": next_candle_utc.isoformat(), "entry_time_bd": entry_time_text,
        "entry_delay_seconds": max(0, int((next_candle_utc - signal_at_utc).total_seconds())),
        "timeframe": "MM-free Price Action / 1m", "entry_timeframe": "1m", "automatic": automatic,
        "mmc_level_type": level_info[0] if level_info else None,
        "mmc_level_price": level_info[1] if level_info else None,
    }


def pd_timestamp_to_utc(value) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
