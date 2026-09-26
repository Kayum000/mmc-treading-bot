"""Signal generation for Real Forex and Quotex OTC markets."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd

from data.quotex_otc import fetch_quotex_candles, OTC_PAIRS, local_active_asset, local_ticks
from data.otc_markets import display_for_asset, asset_for_display
from strategy.otc_candle_pressure import generate_signal as generate_otc_signal
from strategy.candle_reaction import generate_candle_reaction_signal
from strategy.adaptive_real import generate_adaptive_signal
from signals.future_signal import scan_future_opportunities


def _bengali_reason(reason: str) -> str:
    text = str(reason or "").strip()
    for source, translated in (("BUY", "ক্রয়"), ("SELL", "বিক্রয়"), ("HOLD", "অপেক্ষা"), ("Bullish", "বুলিশ"), ("Bearish", "বিয়ারিশ")):
        text = text.replace(source, translated)
    return text


def _hold_condition(reason: str, regime: str = "", strategy: str = "") -> str:
    """Return a clear Bengali explanation of why the signal is HOLD."""
    raw = str(reason or "").strip().lower()
    if "insufficient candle history" in raw:
        return "পর্যাপ্ত ১-মিনিট বন্ধ candle history নেই"
    if "trend alignment absent" in raw:
        return "Trend-এর EMA20/EMA50 alignment নিশ্চিত হয়নি"
    if "breakout not confirmed" in raw:
        return "২০-bar high/low breakout নিশ্চিত হয়নি"
    if "mean-reversion setup absent" in raw:
        return "Bollinger Band + RSI mean-reversion setup পাওয়া যায়নি"
    if "high volatility without clean breakout" in raw:
        return "Volatility বেশি, কিন্তু পরিষ্কার breakout পাওয়া যায়নি"
    if "market regime unclear" in raw:
        return "Market regime পরিষ্কারভাবে শনাক্ত হয়নি"
    return _bengali_reason(reason) or "BUY/SELL-এর প্রয়োজনীয় confirmation পাওয়া যায়নি"


def _strategy_result(candles: pd.DataFrame, ticks: pd.DataFrame | None, strategy_mode: str, otc: bool = False):
    """Select the requested strategy without changing the existing default path."""
    if strategy_mode == "candle_reaction":
        return generate_candle_reaction_signal(candles)
    return generate_otc_signal(candles, ticks=ticks) if otc else generate_adaptive_signal(candles, ticks=ticks)


def _real_signal(pair: str, automatic: bool, strategy_mode: str = "normal") -> dict:
    from quotex_browser_ingest import _REAL_MARKET, _REAL_MARKET_LOCK, real_market_ticks
    # During minute N, analyze only the fully closed candle N-1.
    # Minute N is the next 1-minute candle and therefore the entry candle.
    signal_at_utc = datetime.now(timezone.utc)
    current_minute = signal_at_utc.replace(second=0, microsecond=0)
    # When AUTO requests a few seconds before the minute boundary, prepare the
    # signal for the upcoming candle instead of waiting for that candle to start.
    signal_candle = current_minute + timedelta(minutes=1)
    asset = "".join(ch for ch in pair.upper() if ch.isalnum() or ch in "._-")

    with _REAL_MARKET_LOCK:
        state = dict(_REAL_MARKET.get(asset) or {})
        candle_rows = list(state.get("bars") or [])[-80:]
    # Real quotes are stored in quote_history. Build the same normalized tick
    # DataFrame used by the shared adaptive strategy; do this after releasing
    # the market lock because real_market_ticks() acquires the same lock.
    ticks = real_market_ticks(asset, count=1000)
    if ticks.empty:
        ticks = None
    candles = pd.DataFrame(candle_rows)
    if not candles.empty:
        candles["timestamp"] = pd.to_datetime(candles["timestamp"], unit="s", utc=True, errors="coerce")
        candles = candles.dropna(subset=["timestamp"])
        candles = candles[candles["timestamp"] < current_minute].reset_index(drop=True)

    min_history = 22 if strategy_mode == "candle_reaction" else 60
    if len(candles) < min_history:
        result = _strategy_result(candles, ticks, strategy_mode)
        if result.action in {"BUY", "SELL"}:
            score = int(round(float(result.confidence) * 100))
            is_entry = result.action in {"BUY", "SELL"}
            signal_bd = signal_candle.astimezone(timezone(timedelta(hours=6)))
            return {"pair": pair, "requested_pair": pair, "market_mode": "real", "source": "Quotex Real Market browser WebSocket", "signal": result.action, "market_bias": result.action, "entry_signal": result.action, "buy_score": score if result.action == "BUY" else 0, "sell_score": score if result.action == "SELL" else 0, "reason": _bengali_reason(f"[{result.regime} / {result.strategy}] {result.reason}"), "hold_condition": _hold_condition(result.reason, result.regime, result.strategy) if result.action == "HOLD" else None, "signal_created_utc": signal_at_utc.isoformat(timespec="seconds") if is_entry else None, "signal_created_bd": signal_at_utc.astimezone(timezone(timedelta(hours=6))).strftime("%d %b %Y, %H:%M:%S") if is_entry else None, "signal_time_utc": signal_candle.isoformat(timespec="seconds"), "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "candle_time": signal_candle.isoformat(timespec="seconds"), "analysis_candle_time_utc": None, "entry_price": None, "entry_price_type": "closed_candle_model", "entry_time_utc": signal_candle.isoformat(timespec="seconds"), "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "entry_candle_time_utc": signal_candle.isoformat(timespec="seconds"), "entry_candle_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "entry_delay_seconds": 0, "timeframe": "1-minute closed-candle adaptive", "entry_timeframe": "next 1-minute candle after closed-candle analysis", "automatic": automatic, "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None, "regime": result.regime, "strategy": result.strategy, "strategy_mode": strategy_mode}
        return {
            "pair": pair, "requested_pair": pair, "market_mode": "real",
            "source": "Quotex Real Market browser WebSocket", "signal": "HOLD",
            "market_bias": "HOLD", "entry_signal": "HOLD", "buy_score": 0, "sell_score": 0,
            "reason": "বন্ধ হওয়া ১-মিনিট candle-এর পর্যাপ্ত history পাওয়া যায়নি",
            "hold_condition": "পর্যাপ্ত ১-মিনিট বন্ধ candle history নেই",
            "signal_created_utc": None,
            "signal_created_bd": None,
            "signal_time_utc": None,
            "signal_time_bd": None,
            "candle_time": None, "analysis_candle_time_utc": None,
            "entry_price": None, "entry_price_type": "closed_candle_model",
            "entry_time_utc": None, "entry_time_bd": None, "entry_candle_time_utc": None,
            "entry_candle_time_bd": None, "entry_delay_seconds": None,
            "timeframe": "1-minute closed-candle adaptive", "entry_timeframe": "next 1-minute candle after closed-candle analysis",
            "automatic": automatic, "confidence": 0.0, "mmc_level_type": None, "mmc_level_price": None,
            "regime": "UNKNOWN", "strategy": "NONE", "strategy_mode": strategy_mode,
        }

    analysis_candle_time = candles.iloc[-1]["timestamp"]
    result = _strategy_result(candles, ticks, strategy_mode)
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
        "signal_created_utc": signal_at_utc.isoformat(timespec="seconds"), "signal_created_bd": signal_at_utc.astimezone(timezone(timedelta(hours=6))).strftime("%d %b %Y, %H:%M:%S"),
        "buy_score": score if result.action == "BUY" else 0, "sell_score": score if result.action == "SELL" else 0,
        "reason": _bengali_reason(reason), "hold_condition": _hold_condition(result.reason, regime, strategy_name) if result.action == "HOLD" else None, "signal_time_utc": signal_candle.isoformat(timespec="seconds"),
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


def _otc_signal(pair: str, automatic: bool, strategy_mode: str = "normal") -> dict:
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
    current_minute = signal_at_utc.replace(second=0, microsecond=0)
    # AUTO is scheduled a few seconds before the boundary so the signal is
    # prepared for the upcoming entry candle before that candle starts.
    signal_candle = current_minute + timedelta(minutes=1)

    # The OTC collector already publishes only fully completed 1-minute candles.
    # Match Real-Market timing: analyze the latest closed candle and use the
    # current/next 1-minute candle as the entry candle.
    # Do not apply a second server-clock filter here; small clock skew between
    # the local collector and Render can otherwise hide the newest valid candle
    # exactly at the minute boundary.
    # The adaptive Real strategy requires at least 60 closed candles.
    candles = fetch_quotex_candles(asset, count=80)

    ticks = local_ticks(asset)
    result = _strategy_result(candles, ticks, strategy_mode, otc=True)
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
        "signal_created_utc": signal_at_utc.isoformat(timespec="seconds") if is_entry else None, "signal_created_bd": signal_at_utc.astimezone(timezone(timedelta(hours=6))).strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
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
        "regime": result.regime, "strategy": result.strategy, "strategy_mode": strategy_mode,
    }


def pd_timestamp_utc(value) -> str:
    stamp = value.to_pydatetime(warn=False) if hasattr(value, "to_pydatetime") else value
    stamp = stamp.astimezone(timezone.utc)
    return stamp.isoformat(timespec="milliseconds")


def get_signal(pair: str, market_mode: str = "real", automatic: bool = False, strategy_mode: str = "normal") -> dict:
    pair = (pair or "").strip().upper()
    mode = market_mode.strip().lower()
    strategy_mode = str(strategy_mode or "normal").strip().lower()
    if strategy_mode not in {"normal", "candle_reaction"}:
        raise ValueError("Unsupported strategy mode")
    if mode == "real":
        if not pair:
            raise ValueError("No real market selected")
        return _real_signal(pair, automatic, strategy_mode)
    if mode == "quotex_otc":
        return _otc_signal(pair, automatic, strategy_mode)
    raise ValueError("Unsupported market mode")


def get_future_signals(pair: str, market_mode: str = "real", strategy_mode: str = "normal", limit: int = 15) -> dict:
    """Return ranked forward opportunities for the currently selected pair."""
    pair = (pair or "").strip().upper()
    mode = (market_mode or "real").strip().lower()
    strategy_mode = str(strategy_mode or "normal").strip().lower()
    limit = max(1, min(int(limit or 15), 15))
    if mode == "real":
        from quotex_browser_ingest import _REAL_MARKET, _REAL_MARKET_LOCK, real_market_ticks
        asset = "".join(ch for ch in pair if ch.isalnum() or ch in "._-")
        with _REAL_MARKET_LOCK:
            rows = list((_REAL_MARKET.get(asset) or {}).get("bars") or [])[-100:]
        candles = pd.DataFrame(rows)
        if not candles.empty:
            candles["timestamp"] = pd.to_datetime(candles["timestamp"], unit="s", utc=True, errors="coerce")
            now_minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            candles = candles.dropna(subset=["timestamp"])
            candles = candles[candles["timestamp"] < now_minute].reset_index(drop=True)
        ticks = real_market_ticks(asset, count=1000)
        if ticks.empty:
            ticks = None
    elif mode == "quotex_otc":
        asset = asset_for_display(pair)
        if not asset or asset not in OTC_PAIRS:
            raise RuntimeError("বর্তমান Quotex OTC মার্কেট শনাক্ত করা যায়নি।")
        candles = fetch_quotex_candles(asset, count=100)
        ticks = local_ticks(asset)
    else:
        raise ValueError("Unsupported market mode")
    result = scan_future_opportunities(candles, ticks=ticks, strategy_mode=strategy_mode, limit=limit)
    result.update({"pair": pair, "market_mode": mode})
    return result
