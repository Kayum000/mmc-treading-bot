"""Signal generation for Real Forex and Quotex OTC markets."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from data.quotex_otc import fetch_quotex_candles, OTC_PAIRS, local_active_asset
from data.otc_markets import display_for_asset, asset_for_display
from strategy.tick_run_pressure import generate_signal as generate_forex_signal
from strategy.otc_candle_pressure import generate_signal as generate_otc_signal


def _bengali_reason(reason: str) -> str:
    text = str(reason or "").strip()
    for source, translated in (("BUY", "ক্রয়"), ("SELL", "বিক্রয়"), ("HOLD", "অপেক্ষা"), ("Bullish", "বুলিশ"), ("Bearish", "বিয়ারিশ")):
        text = text.replace(source, translated)
    return text


def _real_signal(pair: str, automatic: bool) -> dict:
    from quotex_browser_ingest import real_market_ticks

    signal_at_utc = datetime.now(timezone.utc)
    asset = "".join(ch for ch in pair.upper() if ch.isalnum() or ch in "._-")
    ticks = real_market_ticks(asset, count=1000)
    if ticks is None or ticks.empty:
        raise RuntimeError("No live Quotex Real Market quote data is available")
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
        "pair": pair, "requested_pair": pair, "market_mode": "real", "source": "Quotex Real Market browser WebSocket",
        "signal": result.action, "market_bias": result.action, "entry_signal": result.action,
        "buy_score": 1 if result.action == "BUY" else 0, "sell_score": 1 if result.action == "SELL" else 0,
        "reason": _bengali_reason(result.reason), "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": candle.isoformat(timespec="seconds") if is_entry else None,
        "analysis_candle_time_utc": tick_time.isoformat(timespec="milliseconds"),
        "entry_price": float((last["askPrice"] + last["bidPrice"]) / 2), "entry_price_type": "latest_quotex_quote_reference",
        "entry_time_utc": signal_at_utc.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_candle_time_utc": candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_candle_time_bd": candle.astimezone(timezone(timedelta(hours=6))).strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": 0 if is_entry else None, "timeframe": "tick-run v2.1",
        "entry_timeframe": "signal candle (current 1-minute candle)", "automatic": automatic,
        "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None,
    }


def _otc_signal(pair: str, automatic: bool) -> dict:
    requested_pair = str(pair or "").strip().upper()
    detected_asset = local_active_asset()
    if detected_asset:
        pair = display_for_asset(detected_asset) or requested_pair
    else:
        pair = requested_pair
    asset = asset_for_display(pair)
    if not asset or asset not in OTC_PAIRS:
        raise RuntimeError("বর্তমান Quotex OTC মার্কেট শনাক্ত করা যায়নি। Quotex-এ একটি 1-minute OTC chart খোলা রাখুন।")

    # Keep the existing OTC candle-pressure strategy unchanged.
    # Only the data source/market selection is now dynamic.
    signal_at_utc = datetime.now(timezone.utc)
    candles = fetch_quotex_candles(asset, count=240)
    result = generate_otc_signal(candles)
    last = candles.iloc[-1]
    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    is_entry = result.action in {"BUY", "SELL"}
    signal_candle = signal_at_utc.replace(second=0, microsecond=0)
    return {
        "pair": pair, "requested_pair": requested_pair, "detected_asset": asset, "market_mode": "quotex_otc",
        "source": "Quotex OTC local Windows/Android screen collector", "signal": result.action, "market_bias": result.action,
        "entry_signal": result.action, "buy_score": 1 if result.action == "BUY" else 0,
        "sell_score": 1 if result.action == "SELL" else 0, "reason": _bengali_reason(result.reason),
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"), "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "analysis_candle_time_utc": pd_timestamp_utc(last["timestamp"]),
        "entry_price": float(last["close"]), "entry_price_type": "latest_closed_otc_candle_reference",
        "entry_time_utc": signal_at_utc.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_candle_time_utc": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_candle_time_bd": signal_candle.astimezone(timezone(timedelta(hours=6))).strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": 0 if is_entry else None,
        "timeframe": "1-minute OTC candle pressure", "entry_timeframe": "signal candle (current 1-minute candle)",
        "automatic": automatic, "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None,
    }


def pd_timestamp_utc(value) -> str:
    stamp = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    stamp = stamp.astimezone(timezone.utc)
    return stamp.isoformat(timespec="milliseconds")


def get_signal(pair: str, market_mode: str = "real", automatic: bool = False) -> dict:
    pair = (pair or "").strip().upper()
    mode = market_mode.strip().lower()
    if mode == "real":
        if not pair:
            raise ValueError("No real market selected")
        return _real_signal(pair, automatic)
    if mode == "quotex_otc":
        return _otc_signal(pair, automatic)
    raise ValueError("Unsupported market mode")
