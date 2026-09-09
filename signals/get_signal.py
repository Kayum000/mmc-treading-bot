"""Live 1-minute signal generation using the tick-pressure strategy."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from data.biquote_forex import fetch_tick_history
from strategy.tick_run_pressure import generate_signal


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


def get_signal(pair: str, market_mode: str = "real", automatic: bool = False) -> dict:
    pair = pair.strip().upper()
    market_mode = market_mode.strip().lower()
    if not pair:
        raise ValueError("No market selected")
    if market_mode != "real":
        raise ValueError("The 1-minute tick-pressure strategy is enabled for real Forex only")

    signal_at_utc = datetime.now(timezone.utc)
    # The browser AUTO SIGNAL scheduler requests this once per minute.
    # Use a fresh tick window for every 1-minute decision instead of candle history.
    ticks = fetch_tick_history(pair, count=1200)
    result = generate_signal(ticks, run_length=3, microprice_threshold=0.40)

    last = ticks.iloc[-1]
    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    tick_time = last["timestamp"]
    if hasattr(tick_time, "to_pydatetime"):
        tick_time = tick_time.to_pydatetime()
    tick_time = tick_time.astimezone(timezone.utc)

    is_entry = result.action in {"BUY", "SELL"}
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
        "candle_time": None,
        "analysis_candle_time_utc": tick_time.isoformat(timespec="milliseconds"),
        "entry_price": float((last["askPrice"] + last["bidPrice"]) / 2),
        "entry_price_type": "latest_tick_mid",
        "entry_time_utc": signal_at_utc.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": 0 if is_entry else None,
        "timeframe": "1m",
        "entry_timeframe": "1-minute signal",
        "automatic": automatic,
        "confidence": result.confidence,
        "mmc_level_type": None,
        "mmc_level_price": None,
    }
