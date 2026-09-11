"""Live signal generation for Real Forex v2.1 and the separate Crypto candle path."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import time

from data.biquote_forex import fetch_tick_history
from strategy.tick_run_pressure import generate_signal as generate_forex_signal
from data.binance_crypto import fetch_crypto_multi_timeframe
from strategy.signal import generate_signal as generate_crypto_signal

ENTRY_LEAD_SECONDS = 30


def _bengali_reason(reason: str) -> str:
    text = str(reason or "").strip()
    replacements = (
        ("BUY", "ক্রয়"), ("SELL", "বিক্রয়"), ("HOLD", "ট্রেড নয়"),
        ("upward run", "উর্ধ্বমুখী tick run"),
        ("downward run", "নিম্নমুখী tick run"),
        ("microprice pressure", "microprice চাপ"),
        ("microprice volume unavailable", "microprice volume পাওয়া যায়নি"),
        ("run and microprice pressure are not aligned", "tick run ও microprice চাপ একই দিকে নেই"),
        ("spread too wide", "spread বেশি"),
        ("insufficient tick history", "পর্যাপ্ত tick history নেই"),
        ("run confirmation absent", "tick-run confirmation পাওয়া যায়নি"),
    )
    for source, translated in replacements:
        text = text.replace(source, translated)
    return text


def _next_candle_boundary_utc(now_utc: datetime) -> datetime:
    epoch = int(now_utc.timestamp())
    return datetime.fromtimestamp(((epoch // 60) + 1) * 60, tz=timezone.utc)


def _get_crypto_signal(pair: str, automatic: bool) -> dict:
    requested_at_utc = datetime.now(timezone.utc)
    next_candle_utc = _next_candle_boundary_utc(requested_at_utc)
    signal_at_utc = next_candle_utc - timedelta(seconds=ENTRY_LEAD_SECONDS)
    wait_seconds = (signal_at_utc - requested_at_utc).total_seconds()
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    signal_at_utc = datetime.now(timezone.utc)
    frames = fetch_crypto_multi_timeframe(pair.replace("/", ""))
    result = generate_crypto_signal(frames)
    latest = frames["1m"]
    last = latest.iloc[-1]
    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    entry_bd = next_candle_utc.astimezone(timezone(timedelta(hours=6)))
    is_entry = result.action in {"BUY", "SELL"}

    return {
        "pair": pair,
        "requested_pair": pair,
        "market_mode": "crypto",
        "source": "Binance spot candles",
        "signal": result.action,
        "market_bias": result.action,
        "entry_signal": result.action,
        "buy_score": result.buy_score,
        "sell_score": result.sell_score,
        "reason": result.reason,
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": str(latest.index[-1]),
        "analysis_candle_time_utc": last["timestamp"].isoformat(),
        "entry_price": float(last["close"]),
        "entry_price_type": "latest_1m_close_reference",
        "entry_time_utc": next_candle_utc.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": entry_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_candle_time_utc": next_candle_utc.isoformat(timespec="seconds") if is_entry else None,
        "entry_candle_time_bd": entry_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": ENTRY_LEAD_SECONDS if is_entry else None,
        "timeframe": "1m entry / 5m + 15m confirmation",
        "entry_timeframe": "next 1-minute candle",
        "automatic": automatic,
        "confidence": None,
        "mmc_level_type": None,
        "mmc_level_price": None,
    }


def get_signal(pair: str, market_mode: str = "real", automatic: bool = False) -> dict:
    pair = pair.strip().upper()
    market_mode = market_mode.strip().lower()
    if not pair:
        raise ValueError("No market selected")
    if market_mode == "crypto":
        return _get_crypto_signal(pair, automatic)
    if market_mode != "real":
        raise ValueError("Unsupported market mode")

    signal_at_utc = datetime.now(timezone.utc)
    ticks = fetch_tick_history(pair, count=1000)
    result = generate_forex_signal(
        ticks,
        run_length=3,
        microprice_threshold=0.40,
    )

    last = ticks.iloc[-1]
    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    tick_time = last["timestamp"]
    if hasattr(tick_time, "to_pydatetime"):
        tick_time = tick_time.to_pydatetime()
    tick_time = tick_time.astimezone(timezone.utc)

    is_entry = result.action in {"BUY", "SELL"}
    signal_candle_utc = signal_at_utc.replace(second=0, microsecond=0)
    signal_candle_bd = signal_candle_utc.astimezone(timezone(timedelta(hours=6)))

    return {
        "pair": pair,
        "requested_pair": pair,
        "market_mode": market_mode,
        "source": "BiQuote tick history",
        "signal": result.action,
        "market_bias": result.action,
        "entry_signal": result.action,
        "buy_score": 1 if result.action == "BUY" else 0,
        "sell_score": 1 if result.action == "SELL" else 0,
        "reason": _bengali_reason(result.reason),
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": signal_candle_utc.isoformat(timespec="seconds") if is_entry else None,
        "analysis_candle_time_utc": tick_time.isoformat(timespec="milliseconds"),
        "entry_price": float((last["askPrice"] + last["bidPrice"]) / 2),
        "entry_price_type": "latest_tick_mid_reference",
        "entry_time_utc": signal_at_utc.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_candle_time_utc": signal_candle_utc.isoformat(timespec="seconds") if is_entry else None,
        "entry_candle_time_bd": signal_candle_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": 0 if is_entry else None,
        "timeframe": "tick-run v2.1",
        "entry_timeframe": "signal candle (current 1-minute candle)",
        "automatic": automatic,
        "confidence": result.confidence,
        "mmc_level_type": None,
        "mmc_level_price": None,
    }
