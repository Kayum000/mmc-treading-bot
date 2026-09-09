"""Live 1-minute signal generation using the existing displacement strategy."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from data.biquote_forex import fetch_forex_candles, fetch_latest_tick
from strategy.tick_run_pressure import generate_candle_signal


def _bengali_reason(reason: str) -> str:
    text = str(reason or "").strip()
    replacements = (
        ("BUY", "ক্রয়"), ("SELL", "বিক্রয়"), ("HOLD", "ট্রেড নয়"),
        ("upward", "উর্ধ্বমুখী"),
        ("downward", "নিম্নমুখী"),
        ("candle run and displacement disagree", "candle run ও displacement একই দিকে নেই"),
        ("spread too wide", "spread বেশি"),
        ("insufficient 1-minute candle history", "পর্যাপ্ত 1-minute candle history নেই"),
        ("short candle-run confirmation absent", "কমপক্ষে ২টি একই দিকের 1-minute candle পাওয়া যায়নি"),
        ("five-candle displacement below threshold", "৫-candle displacement ৭ pip-এর নিচে"),
        ("five-candle displacement unavailable", "৫-candle displacement পাওয়া যায়নি"),
    )
    for source, translated in replacements:
        text = text.replace(source, translated)
    return text


def get_signal(pair: str, market_mode: str = "real", automatic: bool = False) -> dict:
    pair = pair.strip().upper()
    market_mode = market_mode.strip().lower()
    if not pair:
        raise ValueError("No market selected")
    if market_mode != "real":
        raise ValueError("The 1-minute candle displacement strategy is enabled for real Forex only")

    signal_at_utc = datetime.now(timezone.utc)

    # Analyze only completed 1-minute candles. The current forming candle is excluded
    # by fetch_forex_candles(), so the signal cannot change because of an unfinished bar.
    candles = fetch_forex_candles(pair, interval="1min", outputsize=200)
    result = generate_candle_signal(candles, min_run_length=2, displacement_pips=7.0)

    latest_tick = fetch_latest_tick(pair)
    try:
        ask = float(latest_tick["ask"])
        bid = float(latest_tick["bid"])
        entry_price = (ask + bid) / 2.0
    except (KeyError, TypeError, ValueError):
        last_candle = candles.iloc[-1]
        entry_price = float(last_candle["close"])

    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    candle_time = candles.iloc[-1]["timestamp"]
    if hasattr(candle_time, "to_pydatetime"):
        candle_time = candle_time.to_pydatetime()
    candle_time = candle_time.astimezone(timezone.utc)

    # Entry is aligned to the OPEN of the next 1-minute candle. The signal itself
    # is still generated from the latest completed candle(s).
    next_candle_utc = signal_at_utc.replace(second=0, microsecond=0) + timedelta(minutes=1)
    next_candle_bd = next_candle_utc.astimezone(timezone(timedelta(hours=6)))
    entry_delay_seconds = max(0, int((next_candle_utc - signal_at_utc).total_seconds()))
    is_entry = result.action in {"BUY", "SELL"}
    return {
        "pair": pair,
        "requested_pair": pair,
        "market_mode": market_mode,
        "source": "BiQuote completed 1-minute candles",
        "signal": result.action,
        "market_bias": result.action,
        "entry_signal": result.action,
        "buy_score": 1 if result.action == "BUY" else 0,
        "sell_score": 1 if result.action == "SELL" else 0,
        "reason": _bengali_reason(result.reason),
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": candle_time.isoformat(timespec="seconds"),
        "analysis_candle_time_utc": candle_time.isoformat(timespec="milliseconds"),
        "entry_price": entry_price,
        "entry_price_type": "latest_tick_mid",
        "entry_time_utc": next_candle_utc.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": next_candle_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": entry_delay_seconds if is_entry else None,
        "timeframe": "1m",
        "entry_timeframe": "1-minute candle",
        "automatic": automatic,
        "confidence": result.confidence,
        "mmc_level_type": None,
        "mmc_level_price": None,
    }
