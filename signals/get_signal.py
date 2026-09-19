"""Signal generation for Real Forex and Quotex OTC markets."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd

from data.quotex_otc import fetch_quotex_candles, OTC_PAIRS, local_active_asset
from data.otc_markets import display_for_asset, asset_for_display
from strategy.otc_candle_pressure import generate_signal as generate_otc_signal


def _bengali_reason(reason: str) -> str:
    text = str(reason or "").strip()
    for source, translated in (("BUY", "ক্রয়"), ("SELL", "বিক্রয়"), ("HOLD", "অপেক্ষা"), ("Bullish", "বুলিশ"), ("Bearish", "বিয়ারিশ")):
        text = text.replace(source, translated)
    return text


def _real_signal(pair: str, automatic: bool) -> dict:
    from quotex_browser_ingest import _REAL_MARKET, _REAL_MARKET_LOCK
    from strategy.adaptive_real import generate_adaptive_signal

    # During minute N, analyze only the fully closed candle N-1.
    # Minute N is the next 1-minute candle and therefore the entry candle.
    signal_at_utc = datetime.now(timezone.utc)
    signal_candle = signal_at_utc.replace(second=0, microsecond=0)
    asset = "".join(ch for ch in pair.upper() if ch.isalnum() or ch in "._-")

    with _REAL_MARKET_LOCK:
        state = dict(_REAL_MARKET.get(asset) or {})
        candle_rows = list(state.get("bars") or [])[-80:]
        ticks = state.get("ticks")
    candles = pd.DataFrame(candle_rows)
    if not candles.empty:
        candles["timestamp"] = pd.to_datetime(candles["timestamp"], unit="s", utc=True, errors="coerce")
        candles = candles.dropna(subset=["timestamp"])
        candles = candles[candles["timestamp"] < signal_candle].reset_index(drop=True)

    if len(candles) < 60:
        result = generate_adaptive_signal(candles, ticks=ticks)
        if result.action in {"BUY", "SELL"}:
            score = int(round(float(result.confidence) * 100))
            signal_bd = signal_candle.astimezone(timezone(timedelta(hours=6)))
            return {"pair": pair, "requested_pair": pair, "market_mode": "real", "source": "Quotex Real Market browser WebSocket", "signal": result.action, "market_bias": result.action, "entry_signal": result.action, "buy_score": score if result.action == "BUY" else 0, "sell_score": score if result.action == "SELL" else 0, "reason": _bengali_reason(f"[{result.regime} / {result.strategy}] {result.reason}"), "signal_time_utc": signal_candle.isoformat(timespec="seconds"), "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "candle_time": signal_candle.isoformat(timespec="seconds"), "analysis_candle_time_utc": None, "entry_price": None, "entry_price_type": "closed_candle_model", "entry_time_utc": signal_candle.isoformat(timespec="seconds"), "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "entry_candle_time_utc": signal_candle.isoformat(timespec="seconds"), "entry_candle_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "entry_delay_seconds": 0, "timeframe": "1-minute closed-candle adaptive", "entry_timeframe": "next 1-minute candle after closed-candle analysis", "automatic": automatic, "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None, "regime": result.regime, "strategy": result.strategy}
        return {
            "pair": pair, "requested_pair": pair, "market_mode": "real",
            "source": "Quotex Real Market browser WebSocket", "signal": "HOLD",
            "market_bias": "HOLD", "entry_signal": "HOLD", "buy_score": 0, "sell_score": 0,
            "reason": "বন্ধ হওয়া ১-মিনিট candle-এর পর্যাপ্ত history পাওয়া যায়নি",
            "signal_time_utc": signal_candle.isoformat(timespec="seconds"),
            "signal_time_bd": signal_candle.astimezone(timezone(timedelta(hours=6))).strftime("%d %b %Y, %H:%M:%S"),
            "candle_time": None, "analysis_candle_time_utc": None,
            "entry_price": None, "entry_price_type": "closed_candle_model",
            "entry_time_utc": None, "entry_time_bd": None, "entry_candle_time_utc": None,
            "entry_candle_time_bd": None, "entry_delay_seconds": None,
            "timeframe": "1-minute closed-candle adaptive", "entry_timeframe": "next 1-minute candle after closed-candle analysis",
            "automatic": automatic, "confidence": 0.0, "mmc_level_type": None, "mmc_level_price": None,
            "regime": "UNKNOWN", "strategy": "NONE",
        }

    analysis_candle_time = candles.iloc[-1]["timestamp"]
    result = generate_adaptive_signal(candles, ticks=ticks)
    timeframe = f"1-minute/{result.strategy.lower()}"
    regime = result.regime
    strategy_name = result.strategy
    signal_bd = signal_candle.astimezone(timezone(timedelta(hours=6)))
    analysis_time = analysis_candle_time.to_pydatetime(warn=False).astimezone(timezone.utc)
    is_entry = result.action in {"BUY", "SELL"}
    score = int(round(float(result.confidence) * 100)) if is_entry else 0
    reason = f"[{regime} / {strategy_name}] {result.reason}"

    entry_price = None
    if isinstance(ticks, pd.DataFrame) and not ticks.empty:
        last = ticks.iloc[-1]
        if "askPrice" in last and "bidPrice" in last:
            entry_price = float((last["askPrice"] + last["bidPrice"]) / 2)
    return {
        "pair": pair, "requested_pair": pair, "market_mode": "real", "source": "Quotex Real Market browser WebSocket",
        "signal": result.action, "market_bias": result.action, "entry_signal": result.action,
        "buy_score": score if result.action == "BUY" else 0, "sell_score": score if result.action == "SELL" else 0,
        "reason": _bengali_reason(reason), "signal_time_utc": signal_candle.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "analysis_candle_time_utc": analysis_time.isoformat(timespec="milliseconds"),
        "signal_candle_open": float(candles.iloc[-1]["open"]), "signal_candle_close": float(candles.iloc[-1]["close"]),
        "signal_candle_color": "green" if float(candles.iloc[-1]["close"]) > float(candles.iloc[-1]["open"]) else "red" if float(candles.iloc[-1]["close"]) < float(candles.iloc[-1]["open"]) else "doji",
        "entry_price": entry_price, "entry_price_type": "latest_quotex_quote_reference",
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
    if requested_pair in {display_for_asset(asset) for asset in OTC_PAIRS}:
        pair = requested_pair
    elif detected_pair:
        pair = detected_pair
    else:
        pair = requested_pair
    asset = asset_for_display(pair)
    if not asset or asset not in OTC_PAIRS:
        raise RuntimeError("বর্তমান Quotex OTC মার্কেট শনাক্ত করা যায়নি। Quotex-এ একটি 1-minute OTC chart খোলা রাখুন।")

    signal_at_utc = datetime.now(timezone.utc)
    signal_candle = signal_at_utc.replace(second=0, microsecond=0)

    # The OTC collector already publishes only fully completed 1-minute candles.
    # Match Real-Market timing: analyze the latest closed candle and use the
    # current/next 1-minute candle as the entry candle.
    # Do not apply a second server-clock filter here; small clock skew between
    # the local collector and Render can otherwise hide the newest valid candle
    # exactly at the minute boundary.
    # The adaptive Real strategy requires at least 60 closed candles.
    candles = fetch_quotex_candles(asset, count=80)

    result = generate_otc_signal(candles)
    last = candles.iloc[-1] if not candles.empty else None
    signal_bd = signal_candle.astimezone(timezone(timedelta(hours=6)))
    is_entry = result.action in {"BUY", "SELL"}
    score = int(round(float(result.confidence) * 100)) if is_entry else 0
    return {
        "pair": pair, "requested_pair": requested_pair, "detected_asset": asset, "market_mode": "quotex_otc",
        "source": "Quotex OTC local Windows/Android screen collector + Real adaptive strategy",
        "signal": result.action, "market_bias": result.action,
        "entry_signal": result.action, "buy_score": score if result.action == "BUY" else 0,
        "sell_score": score if result.action == "SELL" else 0, "reason": _bengali_reason(f"[{result.regime} / {result.strategy}] {result.reason}"),
        "signal_time_utc": signal_candle.isoformat(timespec="seconds"), "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "analysis_candle_time_utc": pd_timestamp_utc(last["timestamp"]) if last is not None else None,
        "signal_candle_open": float(last["open"]) if last is not None else None, "signal_candle_close": float(last["close"]) if last is not None else None,
        "signal_candle_color": ("green" if float(last["close"]) > float(last["open"]) else "red" if float(last["close"]) < float(last["open"]) else "doji") if last is not None else "unknown",
        "entry_price": float(last["close"]) if last is not None else None, "entry_price_type": "latest_closed_otc_candle_reference",
        "entry_time_utc": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_candle_time_utc": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_candle_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": 0 if is_entry else None,
        "timeframe": f"1-minute/{result.strategy.lower()}",
        "entry_timeframe": "next 1-minute candle after closed-candle analysis",
        "automatic": automatic, "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None,
        "regime": result.regime, "strategy": result.strategy,
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
