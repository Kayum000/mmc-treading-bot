"""Live single-timeframe clean MMC signal generation for the selected market."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import threading

import pandas as pd

from data.twelve_data_forex import fetch_forex_candles
from data.binance_crypto import fetch_crypto_candles
from strategy.mmc import Signal, generate_signal, level_for_side
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
    """Drop the currently running 1m candle so strategy input is closed-only."""
    if frame is None or frame.empty or "timestamp" not in frame.columns:
        return frame
    current_start = pd.Timestamp.fromtimestamp(_period_start(now_utc), tz="UTC")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return frame.loc[timestamps < current_start].copy()


def _load_frame(pair: str, market_mode: str, now_utc: datetime, automatic: bool):
    """Load only selected-market closed 1m candles; never fetch MTF data."""
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
    """Translate strategy/protection reason text for the UI without changing logic."""
    text = str(reason or "").strip()
    replacements = (
        ("Valid Supply/Demand origin → dynamic impulse measure → 50% equilibrium → AB=CD mirror → structure confluence → rejection → confirmation একসঙ্গে তৈরি হয়নি; তাই signal নেই।",
         "বৈধ Supply/Demand Origin → বাজারের প্রকৃত Impulse Distance পরিমাপ → ৫০% Equilibrium → AB=CD Mirror → Structure Confluence → Rejection → Confirmation—সবগুলো শর্ত একসঙ্গে পূরণ হয়নি; তাই কোনো Signal নেই।"),
        ("Support rejection হয়েছে, কিন্তু valid Supply/Demand origin, dynamic impulse distance, AB=CD mirror এবং সম্পূর্ণ bullish confirmation একসঙ্গে হয়নি; BUY বন্ধ।",
         "Support Rejection হয়েছে, কিন্তু বৈধ Supply/Demand Origin, বাজারের প্রকৃত Impulse Distance, AB=CD Mirror এবং সম্পূর্ণ Bullish Confirmation—সবগুলো একসঙ্গে পূরণ হয়নি; তাই BUY Signal বন্ধ।"),
        ("Resistance rejection হয়েছে, কিন্তু valid Supply/Demand origin, dynamic impulse distance, AB=CD mirror এবং সম্পূর্ণ bearish confirmation একসঙ্গে হয়নি; SELL বন্ধ।",
         "Resistance Rejection হয়েছে, কিন্তু বৈধ Supply/Demand Origin, বাজারের প্রকৃত Impulse Distance, AB=CD Mirror এবং সম্পূর্ণ Bearish Confirmation—সবগুলো একসঙ্গে পূরণ হয়নি; তাই SELL Signal বন্ধ।"),
        ("একই candle-এ দুই দিকের Mirror MMC confirmation এসেছে; তাই entry নেই।",
         "একই Candle-এ BUY ও SELL—দুই দিকের Mirror MMC Confirmation এসেছে; তাই কোনো Entry নেই।"),
        ("পরিষ্কার MMC যাচাইয়ের জন্য পর্যাপ্ত বন্ধ ১ মিনিটের ক্যান্ডেল নেই।",
         "পরিষ্কার MMC যাচাইয়ের জন্য পর্যাপ্ত বন্ধ ১-মিনিটের Candle নেই।"),
        ("পরবর্তী 1m candle-এ entry।", "পরবর্তী ১-মিনিটের Candle-এ Entry।"),
        ("supply-origin", "Supply-Origin"),
        ("demand-origin", "Demand-Origin"),
        ("dynamic mirror distance", "বাজারের প্রকৃত Mirror Distance"),
        ("50% equilibrium", "৫০% Equilibrium"),
        ("AB=CD projected mirror target", "AB=CD অনুযায়ী Mirror Target"),
        ("structure confluence", "Structure Confluence"),
        ("rejection", "Rejection"),
        ("bullish confirmation", "Bullish Confirmation"),
        ("bearish confirmation", "Bearish Confirmation"),
    )
    for source, translated in replacements:
        text = text.replace(source, translated)
    return text


def get_signal(pair: str, market_mode: str = "real", automatic: bool = False) -> dict:
    """Generate one clean-MMC next-1m-candle entry for the selected market.

    Only completed 1m candles are analyzed. Level touch alone never produces a
    signal. Entry is always the next 1m candle, not the currently running one.
    """
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

    pending_reason = pending_trade_reason(market_mode, pair)
    if pending_reason:
        signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
        entry_bd = next_candle_utc.astimezone(timezone(timedelta(hours=6)))
        entry_time_text = entry_bd.strftime("%d %b %Y, %H:%M:%S")
        return {
            "pair": pair, "requested_pair": pair, "market_mode": market_mode,
            "source": "Binance" if market_mode == "crypto" else "Twelve Data", "signal": "NO_TRADE",
            "buy_score": 0, "sell_score": 0,
            "reason": f"{_bengali_reason(pending_reason)} এন্ট্রি হবে {entry_time_text} বাংলাদেশ সময় ({next_candle_utc.strftime('%H:%M:%S')} UTC)।",
            "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
            "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "candle_time": None,
            "analysis_candle_time_utc": None, "entry_price": None, "entry_price_type": "pending_trade_block",
            "entry_time_utc": next_candle_utc.isoformat(timespec="seconds"), "entry_time_bd": entry_time_text,
            "entry_delay_seconds": max(0, int((next_candle_utc - signal_at_utc).total_seconds())),
            "timeframe": "Clean MMC / 1m", "entry_timeframe": "1m", "automatic": automatic,
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
    reason_text = (
        f"{_bengali_reason(result.reason)} "
        f"এন্ট্রি হবে পরবর্তী ১-মিনিটের Candle-এ, সময় {entry_time_text} বাংলাদেশ সময় "
        f"({next_candle_utc.strftime('%H:%M:%S')} UTC)। এটি চলমান Candle-এর জন্য নয়।"
    )

    return {
        "pair": pair, "requested_pair": pair, "market_mode": market_mode,
        "source": "Binance" if market_mode == "crypto" else "Twelve Data", "signal": result.action,
        "buy_score": result.buy_score, "sell_score": result.sell_score, "reason": reason_text,
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "candle_time": candle_time,
        "analysis_candle_time_utc": candle_time, "entry_price": entry_price,
        "entry_price_type": "last_closed_1m_close_reference", "entry_time_utc": next_candle_utc.isoformat(),
        "entry_time_bd": entry_time_text,
        "entry_delay_seconds": max(0, int((next_candle_utc - signal_at_utc).total_seconds())),
        "timeframe": "Clean MMC / 1m", "entry_timeframe": "1m", "automatic": automatic,
        "mmc_level_type": level_info[0] if level_info else None,
        "mmc_level_price": level_info[1] if level_info else None,
    }


def pd_timestamp_to_utc(value) -> datetime:
    """Convert a candle timestamp to an aware UTC datetime."""
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
