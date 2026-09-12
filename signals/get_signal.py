"""Signal generation for Real Forex and Quotex OTC markets."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from data.biquote_forex import fetch_tick_history
from data.quotex_otc import fetch_quotex_candles, OTC_PAIRS
from strategy.tick_run_pressure import generate_signal as generate_forex_signal
from strategy.otc_candle_pressure import generate_signal as generate_otc_signal

OTC_MAP = {
    "EURUSD OTC": "EURUSD_otc", "GBPUSD OTC": "GBPUSD_otc", "USDJPY OTC": "USDJPY_otc",
    "AUDUSD OTC": "AUDUSD_otc", "USDCAD OTC": "USDCAD_otc", "USDCHF OTC": "USDCHF_otc",
    "NZDUSD OTC": "NZDUSD_otc", "EURJPY OTC": "EURJPY_otc", "GBPJPY OTC": "GBPJPY_otc",
    "XAUUSD OTC": "XAUUSD_otc", "USDARS OTC": "USDARS_otc",
}

def _bengali_reason(reason: str) -> str:
    text = str(reason or "").strip()
    for source, translated in (("BUY", "ক্রয়"), ("SELL", "বিক্রয়"), ("HOLD", "অপেক্ষা"), ("Bullish", "বুলিশ"), ("Bearish", "বিয়ারিশ")):
        text = text.replace(source, translated)
    return text

def _real_signal(pair: str, automatic: bool) -> dict:
    signal_at_utc = datetime.now(timezone.utc)
    ticks = fetch_tick_history(pair, count=1000)
    if ticks is None or ticks.empty:
        raise RuntimeError("No live tick data was returned")
    result = generate_forex_signal(ticks, run_length=3, microprice_threshold=0.40)
    last = ticks.iloc[-1]
    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    tick_time = last["timestamp"]
    if hasattr(tick_time, "to_pydatetime"):
        tick_time = tick_time.to_pydatetime()
    tick_time = tick_time.astimezone(timezone.utc)
    is_entry = result.action in {"BUY", "SELL"}
    candle = signal_at_utc.replace(second=0, microsecond=0)
    return {
        "pair": pair, "requested_pair": pair, "market_mode": "real", "source": "BiQuote tick history",
        "signal": result.action, "market_bias": result.action, "entry_signal": result.action,
        "buy_score": 1 if result.action == "BUY" else 0, "sell_score": 1 if result.action == "SELL" else 0,
        "reason": _bengali_reason(result.reason), "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": candle.isoformat(timespec="seconds") if is_entry else None,
        "analysis_candle_time_utc": tick_time.isoformat(timespec="milliseconds"),
        "entry_price": float((last["askPrice"] + last["bidPrice"]) / 2), "entry_price_type": "latest_tick_mid_reference",
        "entry_time_utc": signal_at_utc.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_candle_time_utc": candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_candle_time_bd": candle.astimezone(timezone(timedelta(hours=6))).strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": 0 if is_entry else None, "timeframe": "tick-run v2.1",
        "entry_timeframe": "signal candle (current 1-minute candle)", "automatic": automatic,
        "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None,
    }

def _otc_signal(pair: str, automatic: bool) -> dict:
    asset = OTC_MAP.get(pair)
    if not asset or asset not in OTC_PAIRS:
        raise ValueError("Unsupported Quotex OTC market")
    signal_at_utc = datetime.now(timezone.utc)
    candles = fetch_quotex_candles(asset, count=240)
    result = generate_otc_signal(candles)
    last = candles.iloc[-1]
    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    is_entry = result.action in {"BUY", "SELL"}
    next_candle = (signal_at_utc + timedelta(minutes=1)).replace(second=0, microsecond=0)
    return {
        "pair": pair, "requested_pair": pair, "market_mode": "quotex_otc",
        "source": "Quotex OTC local Android screen collector", "signal": result.action, "market_bias": result.action,
        "entry_signal": result.action, "buy_score": 1 if result.action == "BUY" else 0,
        "sell_score": 1 if result.action == "SELL" else 0, "reason": _bengali_reason(result.reason),
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"), "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": next_candle.isoformat(timespec="seconds") if is_entry else None,
        "analysis_candle_time_utc": pd_timestamp_utc(last["timestamp"]),
        "entry_price": float(last["close"]), "entry_price_type": "latest_closed_otc_candle_reference",
        "entry_time_utc": next_candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": next_candle.astimezone(timezone(timedelta(hours=6))).strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_candle_time_utc": next_candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_candle_time_bd": next_candle.astimezone(timezone(timedelta(hours=6))).strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": max(0, int((next_candle - signal_at_utc).total_seconds())) if is_entry else None,
        "timeframe": "1-minute OTC candle pressure", "entry_timeframe": "next 1-minute candle",
        "automatic": automatic, "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None,
    }

def pd_timestamp_utc(value) -> str:
    stamp = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    stamp = stamp.astimezone(timezone.utc)
    return stamp.isoformat(timespec="milliseconds")

def get_signal(pair: str, market_mode: str = "real", automatic: bool = False) -> dict:
    pair = pair.strip().upper()
    mode = market_mode.strip().lower()
    if not pair:
        raise ValueError("No market selected")
    if mode == "real":
        return _real_signal(pair, automatic)
    if mode == "quotex_otc":
        return _otc_signal(pair, automatic)
    raise ValueError("Unsupported market mode")
