"""Live 1-minute signal generation using the v2.1 tick strategy."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd

from data.biquote_forex import fetch_latest_tick, fetch_tick_history
from strategy.tick_run_pressure import generate_signal


def _bengali_reason(reason: str) -> str:
    text = str(reason or "").strip()
    replacements = (
        ("BUY", "ক্রয়"), ("SELL", "বিক্রয়"), ("HOLD", "ট্রেড নয়"),
        ("upward", "উর্ধ্বমুখী"),
        ("downward", "নিম্নমুখী"),
        ("run and microprice pressure are not aligned", "tick run ও microprice pressure একই দিকে নেই"),
        ("spread too wide", "spread বেশি"),
        ("insufficient tick history", "পর্যাপ্ত tick history নেই"),
        ("run confirmation absent", "প্রয়োজনীয় tick-run confirmation পাওয়া যায়নি"),
        ("microprice pressure", "microprice pressure"),
        ("microprice volume unavailable", "microprice volume পাওয়া যায়নি"),
        ("fast tick confirmation", "দ্রুত tick confirmation"),
        ("fast tick", "দ্রুত tick"),
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
        raise ValueError("The 1-minute v2.1 tick strategy is enabled for real Forex only")

    signal_at_utc = datetime.now(timezone.utc)

    # v2.1 remains fully tick-based. Only the signal window is aligned to
    # the latest fully completed 1-minute candle; the underlying tick rules
    # are unchanged: 3-tick default run, microprice threshold 0.40,
    # spread filter and fast-tick confirmation/fallback.
    ticks = fetch_tick_history(pair, count=1000)
    ticks["timestamp"] = pd.to_datetime(ticks["timestamp"], utc=True, errors="coerce")
    completed_minute = signal_at_utc.replace(second=0, microsecond=0) - timedelta(minutes=1)
    completed_minute_end = completed_minute + timedelta(minutes=1)
    minute_ticks = ticks[
        (ticks["timestamp"] >= completed_minute)
        & (ticks["timestamp"] < completed_minute_end)
    ].copy()
    result = generate_signal(
        minute_ticks,
        run_length=3,
        microprice_threshold=0.40,
    )

    latest_tick = fetch_latest_tick(pair)
    try:
        ask = float(latest_tick["ask"])
        bid = float(latest_tick["bid"])
        entry_price = (ask + bid) / 2.0
    except (KeyError, TypeError, ValueError):
        if not minute_ticks.empty:
            last_tick = minute_ticks.iloc[-1]
            entry_price = (float(last_tick["askPrice"]) + float(last_tick["bidPrice"])) / 2.0
        else:
            entry_price = None

    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    analysis_candle_time = completed_minute.replace(tzinfo=timezone.utc)

    # Entry is aligned to the OPEN of the next 1-minute candle.
    next_candle_utc = signal_at_utc.replace(second=0, microsecond=0) + timedelta(minutes=1)
    next_candle_bd = next_candle_utc.astimezone(timezone(timedelta(hours=6)))
    entry_delay_seconds = max(0, int((next_candle_utc - signal_at_utc).total_seconds()))
    is_entry = result.action in {"BUY", "SELL"}
    return {
        "pair": pair,
        "requested_pair": pair,
        "market_mode": market_mode,
        "source": "BiQuote tick history — v2.1 tick strategy, 1-minute window",
        "strategy_version": "v2.1",
        "signal": result.action,
        "market_bias": result.action,
        "entry_signal": result.action,
        "buy_score": 1 if result.action == "BUY" else 0,
        "sell_score": 1 if result.action == "SELL" else 0,
        "reason": _bengali_reason(result.reason),
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": analysis_candle_time.isoformat(timespec="seconds"),
        "analysis_candle_time_utc": analysis_candle_time.isoformat(timespec="milliseconds"),
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
