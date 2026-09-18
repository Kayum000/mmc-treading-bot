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
    import pandas as pd
    from quotex_browser_ingest import real_market_ticks, _REAL_MARKET, _REAL_MARKET_LOCK
    from strategy.adaptive_real import generate_adaptive_signal

    # A signal requested during minute N must analyze the last fully closed
    # candle (N-1), then use minute N as the entry candle. This prevents the
    # live/incomplete candle from changing the signal after it is issued.
    signal_at_utc = datetime.now(timezone.utc)
    # Always target the NEXT minute boundary. The signal is based only on
    # candles that are fully closed before that entry minute.
    signal_candle = (signal_at_utc.replace(second=0, microsecond=0) + timedelta(minutes=1))
    asset = "".join(ch for ch in pair.upper() if ch.isalnum() or ch in "._-")
    ticks = real_market_ticks(asset, count=200)
    if ticks is None or ticks.empty:
        raise RuntimeError("No live Quotex Real Market quote data is available")

    with _REAL_MARKET_LOCK:
        state = dict(_REAL_MARKET.get(asset) or {})
        candle_rows = list(state.get("bars") or [])[-80:]
    candles = pd.DataFrame(candle_rows)
    if not candles.empty:
        candles["timestamp"] = pd.to_datetime(candles["timestamp"], unit="s", utc=True, errors="coerce")
        candles = candles.dropna(subset=["timestamp"])
        candles = candles[candles["timestamp"] < signal_candle].reset_index(drop=True)

    analysis_candle_time = None
    if len(candles) >= 60:
        analysis_candle_time = candles.iloc[-1]["timestamp"]
        result = generate_adaptive_signal(candles, ticks=ticks)
        timeframe = f"adaptive-real/{result.strategy.lower()}"
        regime = result.regime
        strategy_name = result.strategy
    else:
        fallback = generate_forex_signal(ticks, run_length=3, microprice_threshold=0.40)
        result = type("Signal", (), {"action": fallback.action, "confidence": fallback.confidence, "reason": fallback.reason, "regime": "MICRO_MOVE", "strategy": "TICK_PRESSURE"})()
        timeframe = "adaptive-real/tick-pressure-fallback"
        regime = result.regime
        strategy_name = result.strategy

    last = ticks.iloc[-1]
    signal_bd = signal_candle.astimezone(timezone(timedelta(hours=6)))
    tick_time = last["timestamp"]
    if hasattr(tick_time, "to_pydatetime"):
        tick_time = tick_time.to_pydatetime(warn=False)
    tick_time = tick_time.astimezone(timezone.utc)
    analysis_time = analysis_candle_time
    if analysis_time is not None and hasattr(analysis_time, "to_pydatetime"):
        analysis_time = analysis_time.to_pydatetime(warn=False)
    if analysis_time is None:
        analysis_time = tick_time
    analysis_time = analysis_time.astimezone(timezone.utc)
    is_entry = result.action in {"BUY", "SELL"}
    reason = f"[{regime} / {strategy_name}] {result.reason}"
    return {
        "pair": pair, "requested_pair": pair, "market_mode": "real", "source": "Quotex Real Market browser WebSocket",
        "signal": result.action, "market_bias": result.action, "entry_signal": result.action,
        "buy_score": 1 if result.action == "BUY" else 0, "sell_score": 1 if result.action == "SELL" else 0,
        "reason": _bengali_reason(reason), "signal_time_utc": signal_candle.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "analysis_candle_time_utc": analysis_time.isoformat(timespec="milliseconds"),
        "entry_price": float((last["askPrice"] + last["bidPrice"]) / 2), "entry_price_type": "latest_quotex_quote_reference",
        "entry_time_utc": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_candle_time_utc": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_candle_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": 0 if is_entry else None, "timeframe": timeframe,
        "entry_timeframe": "next 1-minute candle after closed-candle analysis", "automatic": automatic,
        "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None,
        "regime": regime, "strategy": strategy_name,
    }


def _otc_signal(pair: str, automatic: bool) -> dict:
    requested_pair = str(pair or "").strip().upper()
    detected_asset = local_active_asset()
    detected_pair = display_for_asset(detected_asset) if detected_asset else None

    # The selected dashboard pair is authoritative for this request. The
    # collector's active-asset cache is only used when no valid pair was
    # supplied. This prevents a brief collector refresh gap at the minute
    # boundary from changing the requested market or rejecting the signal.
    if requested_pair in {display_for_asset(asset) for asset in OTC_PAIRS}:
        pair = requested_pair
    elif detected_pair:
        pair = detected_pair
    else:
        pair = requested_pair

    asset = asset_for_display(pair)
    if not asset or asset not in OTC_PAIRS:
        raise RuntimeError("বর্তমান Quotex OTC মার্কেট শনাক্ত করা যায়নি। Quotex-এ একটি 1-minute OTC chart খোলা রাখুন।")

    # Keep the existing OTC candle-pressure strategy unchanged.
    # The collector supplies completed candles; the latest one is therefore
    # the candle analyzed, while the current minute is the entry candle.
    signal_at_utc = datetime.now(timezone.utc)
    signal_candle = signal_at_utc.replace(second=0, microsecond=0)
    candles = fetch_quotex_candles(asset, count=60)
    # The entry belongs to the next minute boundary. Exclude any candle that
    # is still inside/at the entry minute so an incomplete candle cannot alter
    # the signal after it has been generated.
    try:
        candle_ts = pd.to_datetime(candles["timestamp"], utc=True, errors="coerce")
        closed = candles.loc[candle_ts < signal_candle].copy()
        if len(closed) >= 1:
            candles = closed.reset_index(drop=True)
    except Exception:
        pass
    result = generate_otc_signal(candles)
    last = candles.iloc[-1]
    signal_bd = signal_candle.astimezone(timezone(timedelta(hours=6)))
    is_entry = result.action in {"BUY", "SELL"}
    return {
        "pair": pair, "requested_pair": requested_pair, "detected_asset": asset, "market_mode": "quotex_otc",
        "source": "Quotex OTC local Windows/Android screen collector", "signal": result.action, "market_bias": result.action,
        "entry_signal": result.action, "buy_score": 1 if result.action == "BUY" else 0,
        "sell_score": 1 if result.action == "SELL" else 0, "reason": _bengali_reason(result.reason),
        "signal_time_utc": signal_candle.isoformat(timespec="seconds"), "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "analysis_candle_time_utc": pd_timestamp_utc(last["timestamp"]),
        "entry_price": float(last["close"]), "entry_price_type": "latest_closed_otc_candle_reference",
        "entry_time_utc": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_candle_time_utc": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_candle_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": 0 if is_entry else None,
        "timeframe": "1-minute OTC candle pressure", "entry_timeframe": "next 1-minute candle after closed-candle analysis",
        "automatic": automatic, "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None,
    }


def pd_timestamp_utc(value) -> str:
    stamp = value.to_pydatetime(warn=False) if hasattr(value, "to_pydatetime") else value
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
