"""Signal generation for Real Forex and Quotex OTC markets."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import time
import os

import pandas as pd

from data.quotex_otc import fetch_quotex_candles, OTC_PAIRS, local_active_asset, local_ticks
from data.otc_markets import display_for_asset, asset_for_display
from strategy.quotex_price_action import generate_quotex_price_action_signal


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
    if "পর্যাপ্ত closed 1-minute candle" in raw or "at least 60" in raw:
        return "পর্যাপ্ত বন্ধ ১-মিনিট candle history নেই"
    if "৫-মিনিটের trend" in raw or "trend পরিষ্কার নয়" in raw:
        return "৫-মিনিটের Trend পরিষ্কার নয়"
    if "confirmation candle দুর্বল" in raw or "doji" in raw:
        return "Confirmation candle দুর্বল বা Doji"
    if "trend, level ও candle confirmation" in raw:
        return "Trend, Support/Resistance ও Confirmation একদিকে মেলেনি"
    if "invalidation level" in raw:
        return "দাম Invalidation Level ভেঙেছে; সেটআপ বাতিল"
    if "পরস্পরবিরোধী setup" in raw:
        return "পরস্পরবিরোধী Setup পাওয়া গেছে"
    if "atr/price range" in raw:
        return "দামের Range নির্ভরযোগ্য নয়"
    return _bengali_reason(reason) or "BUY/SELL-এর প্রয়োজনীয় confirmation পাওয়া যায়নি"


def _entry_candle_time(signal_at_utc: datetime, automatic: bool, latest_closed_open=None) -> datetime:
    """Choose an actionable full-minute entry, accounting for AUTO boundary races.

    AUTO runs just after the minute boundary. If collector/network delivery
    takes a few seconds, reuse the active minute only while its short grace
    window remains and the immediately preceding candle is confirmed closed.
    Otherwise target a future candle rather than publishing a stale entry.
    """
    current_minute = signal_at_utc.replace(second=0, microsecond=0)
    elapsed_seconds = signal_at_utc.second + signal_at_utc.microsecond / 1_000_000
    if automatic and elapsed_seconds <= 8.0 and latest_closed_open is not None:
        try:
            stamp = latest_closed_open.to_pydatetime() if hasattr(latest_closed_open, "to_pydatetime") else latest_closed_open
            if not isinstance(stamp, datetime):
                stamp = pd.to_datetime(stamp, utc=True).to_pydatetime()
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamp = stamp.astimezone(timezone.utc).replace(second=0, microsecond=0)
            if stamp + timedelta(minutes=1) == current_minute:
                return current_minute
        except (TypeError, ValueError, OverflowError):
            pass
    return current_minute + timedelta(minutes=1)


def _entry_delay_seconds(signal_at_utc: datetime, entry_at_utc: datetime) -> int:
    """Seconds until the chosen entry boundary; zero means enter now/already opened."""
    return max(0, int(round((entry_at_utc - signal_at_utc).total_seconds())))


def _twelvedata_real_signal(pair: str, automatic: bool) -> dict:
    """Build the standard signal payload from fresh, completed Twelve Data Forex candles."""
    provider = os.getenv("MARKET_DATA_PROVIDER", "twelvedata").strip().lower()
    if provider == "oanda":
        from data.oanda import fetch_oanda_candles, fetch_oanda_quote, normalize_oanda_instrument
        symbol = normalize_oanda_instrument(pair)
        candles = fetch_oanda_candles(symbol, count=1200)
        live_quote = fetch_oanda_quote(symbol)
        source_label = "OANDA v20 live pricing + completed M1 candles"
    elif provider in {"twelvedata", "twelve_data"}:
        from data.twelve_data import fetch_twelve_data_candles, normalize_forex_symbol
        symbol = normalize_forex_symbol(pair)
        candles = fetch_twelve_data_candles(symbol, count=1200)
        live_quote = None
        source_label = "Twelve Data Forex 1-minute OHLC API"
    else:
        raise RuntimeError("MARKET_DATA_PROVIDER must be 'oanda' or 'twelvedata'.")
    signal_at_utc = datetime.now(timezone.utc)
    latest = candles.iloc[-1]
    latest_open = latest["timestamp"]
    signal_candle = _entry_candle_time(signal_at_utc, automatic, latest_open)
    result = generate_quotex_price_action_signal(candles)
    signal_bd = signal_candle.astimezone(timezone(timedelta(hours=6)))
    is_entry = result.action in {"BUY", "SELL"}
    score = int(round(float(result.confidence) * 100)) if is_entry else 0
    last_close = float(latest["close"])
    return {
        "pair": symbol, "requested_pair": pair, "market_mode": "real",
        "source": source_label,
        "signal": result.action, "market_bias": result.action, "entry_signal": result.action,
        "buy_score": score if result.action == "BUY" else 0,
        "sell_score": score if result.action == "SELL" else 0,
        "reason": _bengali_reason(f"[{result.regime} / {result.strategy}] {result.reason}"),
        "hold_condition": _hold_condition(result.reason, result.regime, result.strategy) if result.action == "HOLD" else None,
        "signal_created_utc": signal_at_utc.isoformat(timespec="seconds") if is_entry else None,
        "signal_created_bd": signal_at_utc.astimezone(timezone(timedelta(hours=6))).strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "signal_time_utc": signal_candle.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "analysis_candle_time_utc": latest_open.to_pydatetime().astimezone(timezone.utc).isoformat(timespec="milliseconds"),
        "signal_candle_open": float(latest["open"]),
        "signal_candle_close": last_close,
        "signal_candle_color": "green" if last_close > float(latest["open"]) else "red" if last_close < float(latest["open"]) else "doji",
        "entry_price": float(live_quote["price"]) if live_quote else last_close,
        "live_quote": live_quote,
        "entry_price_type": "oanda_live_bid_ask_midpoint" if live_quote else "latest_closed_provider_candle_close_reference",
        "entry_time_utc": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_candle_time_utc": signal_candle.isoformat(timespec="seconds") if is_entry else None,
        "entry_candle_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S") if is_entry else None,
        "entry_delay_seconds": _entry_delay_seconds(signal_at_utc, signal_candle) if is_entry else None,
        "timeframe": f"1-minute/{result.strategy.lower()}",
        "entry_timeframe": "next 1-minute candle after closed-candle analysis",
        "automatic": automatic, "confidence": result.confidence,
        "mmc_level_type": None, "mmc_level_price": None,
        "regime": result.regime, "strategy": result.strategy,
        "strategy_mode": "quotex_price_action", "mmc_analysis": result.mmc_analysis,
    }


def _real_signal(pair: str, automatic: bool) -> dict:
    provider = os.getenv("MARKET_DATA_PROVIDER", "twelvedata").strip().lower()
    if provider == "oanda":
        return _twelvedata_real_signal(pair, automatic)
    if provider in {"twelvedata", "twelve_data"} and os.getenv("TWELVEDATA_API_KEY", "").strip():
        return _twelvedata_real_signal(pair, automatic)
    if provider not in {"oanda", "twelvedata", "twelve_data"}:
        raise RuntimeError("MARKET_DATA_PROVIDER must be 'oanda' or 'twelvedata'.")

    from quotex_browser_ingest import _REAL_MARKET, _REAL_MARKET_LOCK, real_market_ticks
    asset = "".join(ch for ch in pair.upper() if ch.isalnum() or ch in "._-")

    # Reject cached Real-Market data when the PC collector has stopped sending updates.
    from quotex_browser_ingest import REAL_MARKET_MAX_AGE_SECONDS
    with _REAL_MARKET_LOCK:
        state_age = (_REAL_MARKET.get(asset) or {}).get("updated_at")
    age_seconds = (time.time() - float(state_age)) if state_age is not None else None
    if age_seconds is None or age_seconds > REAL_MARKET_MAX_AGE_SECONDS:
        raise RuntimeError("Quotex Real Market collector is not connected or has no fresh data.")

    # Only candles whose opening timestamp precedes the current minute may be
    # analyzed. The latest closed candle is passed to the timing helper below.
    signal_at_utc = datetime.now(timezone.utc)
    current_minute = signal_at_utc.replace(second=0, microsecond=0)
    asset = "".join(ch for ch in pair.upper() if ch.isalnum() or ch in "._-")

    with _REAL_MARKET_LOCK:
        state = dict(_REAL_MARKET.get(asset) or {})
        candle_rows = list(state.get("bars") or [])[-1200:]
    # Real quotes are stored in quote_history. Build the same normalized tick
    # DataFrame used by the shared hybrid MMC strategy; do this after releasing
    # the market lock because real_market_ticks() acquires the same lock.
    ticks = real_market_ticks(asset, count=10000)
    if ticks.empty:
        ticks = None
    candles = pd.DataFrame(candle_rows)
    if not candles.empty:
        candles["timestamp"] = pd.to_datetime(candles["timestamp"], unit="s", utc=True, errors="coerce")
        candles = candles.dropna(subset=["timestamp"])
        candles = candles[candles["timestamp"] < current_minute].reset_index(drop=True)

    latest_closed_open = candles.iloc[-1]["timestamp"] if not candles.empty else None
    signal_candle = _entry_candle_time(signal_at_utc, automatic, latest_closed_open)

    min_history = 60
    if len(candles) < min_history:
        result = generate_quotex_price_action_signal(candles)
        if result.action in {"BUY", "SELL"}:
            score = int(round(float(result.confidence) * 100))
            is_entry = result.action in {"BUY", "SELL"}
            signal_bd = signal_candle.astimezone(timezone(timedelta(hours=6)))
            return {"pair": pair, "requested_pair": pair, "market_mode": "real", "source": "Quotex Real Market browser WebSocket", "signal": result.action, "market_bias": result.action, "entry_signal": result.action, "buy_score": score if result.action == "BUY" else 0, "sell_score": score if result.action == "SELL" else 0, "reason": _bengali_reason(f"[{result.regime} / {result.strategy}] {result.reason}"), "hold_condition": _hold_condition(result.reason, result.regime, result.strategy) if result.action == "HOLD" else None, "signal_created_utc": signal_at_utc.isoformat(timespec="seconds") if is_entry else None, "signal_created_bd": signal_at_utc.astimezone(timezone(timedelta(hours=6))).strftime("%d %b %Y, %H:%M:%S") if is_entry else None, "signal_time_utc": signal_candle.isoformat(timespec="seconds"), "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "candle_time": signal_candle.isoformat(timespec="seconds"), "analysis_candle_time_utc": None, "entry_price": None, "entry_price_type": "closed_candle_model", "entry_time_utc": signal_candle.isoformat(timespec="seconds"), "entry_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "entry_candle_time_utc": signal_candle.isoformat(timespec="seconds"), "entry_candle_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"), "entry_delay_seconds": 0, "timeframe": "1-minute closed-candle price action", "entry_timeframe": "next 1-minute candle after closed-candle analysis", "automatic": automatic, "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None, "regime": result.regime, "strategy": result.strategy, "strategy_mode": "quotex_price_action", "mmc_analysis": result.mmc_analysis}
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
            "candle_time": None, "analysis_candle_time_utc": candles.iloc[-1]["timestamp"].to_pydatetime().astimezone(timezone.utc).isoformat(timespec="milliseconds") if not candles.empty else None,
            "entry_price": None, "entry_price_type": "closed_candle_model",
            "entry_time_utc": None, "entry_time_bd": None, "entry_candle_time_utc": None,
            "entry_candle_time_bd": None, "entry_delay_seconds": None,
            "timeframe": "1-minute closed-candle price action", "entry_timeframe": "next 1-minute candle after closed-candle analysis",
            "automatic": automatic, "confidence": 0.0, "mmc_level_type": None, "mmc_level_price": None,
            "regime": "UNKNOWN", "strategy": "NONE", "strategy_mode": "quotex_price_action", "mmc_analysis": result.mmc_analysis,
        }

    analysis_candle_time = candles.iloc[-1]["timestamp"]
    result = generate_quotex_price_action_signal(candles)
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
        "entry_delay_seconds": _entry_delay_seconds(signal_at_utc, signal_candle) if is_entry else None, "timeframe": timeframe,
        "entry_timeframe": "next 1-minute candle after closed-candle analysis", "automatic": automatic,
        "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None,
        "regime": regime, "strategy": strategy_name, "strategy_mode": "quotex_price_action", "mmc_analysis": result.mmc_analysis,
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

    # The OTC collector already publishes only fully completed 1-minute candles.
    # Match Real-Market timing: analyze the latest closed candle and use the
    # current/next 1-minute candle as the entry candle.
    # Do not apply a second server-clock filter here; small clock skew between
    # the local collector and Render can otherwise hide the newest valid candle
    # exactly at the minute boundary.
    # The hybrid MMC strategy requires at least 60 closed candles.
    candles = fetch_quotex_candles(asset, count=1200)
    latest_closed_open = candles.iloc[-1]["timestamp"] if not candles.empty else None
    signal_candle = _entry_candle_time(signal_at_utc, automatic, latest_closed_open)

    ticks = local_ticks(asset)
    result = generate_quotex_price_action_signal(candles)
    last = candles.iloc[-1] if not candles.empty else None
    signal_bd = signal_candle.astimezone(timezone(timedelta(hours=6)))
    is_entry = result.action in {"BUY", "SELL"}
    score = int(round(float(result.confidence) * 100)) if is_entry else 0
    return {
        "pair": pair, "requested_pair": requested_pair, "detected_asset": asset, "market_mode": "quotex_otc",
        "source": "Quotex OTC local Windows/Android screen collector + strict Price Action strategy",
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
        "entry_delay_seconds": _entry_delay_seconds(signal_at_utc, signal_candle) if is_entry else None,
        "timeframe": f"1-minute/{result.strategy.lower()}",
        "entry_timeframe": "next 1-minute candle after closed-candle analysis",
        "automatic": automatic, "confidence": result.confidence, "mmc_level_type": None, "mmc_level_price": None,
        "regime": result.regime, "strategy": result.strategy, "strategy_mode": "quotex_price_action", "mmc_analysis": result.mmc_analysis,
    }



def pd_timestamp_utc(value) -> str:
    stamp = value.to_pydatetime(warn=False) if hasattr(value, "to_pydatetime") else value
    stamp = stamp.astimezone(timezone.utc)
    return stamp.isoformat(timespec="milliseconds")


def get_signal(pair: str, market_mode: str = "real", automatic: bool = False, strategy_mode: str = "normal") -> dict:
    pair = (pair or "").strip().upper()
    mode = market_mode.strip().lower()
    if mode == "real":
        if not pair:
            raise ValueError("No real market selected")
        result = _real_signal(pair, automatic)
    elif mode == "quotex_otc":
        result = _otc_signal(pair, automatic)
    else:
        raise ValueError("Unsupported market mode")

    # All actionable entries use a five-minute expiry measured from the scheduled
    # entry candle boundary. HOLD states never expose a fake expiry timestamp.
    result["expiry_minutes"] = 5
    entry_stamp = result.get("signal_time_utc") or result.get("entry_time_utc")
    if result.get("signal") in {"BUY", "SELL"} and entry_stamp:
        entry_dt = pd.to_datetime(entry_stamp, utc=True, errors="coerce")
        if not pd.isna(entry_dt):
            expiry_dt = entry_dt + pd.Timedelta(minutes=5)
            result["expiry_time_utc"] = expiry_dt.isoformat(timespec="seconds")
            result["expiry_time_bd"] = expiry_dt.tz_convert("Asia/Dhaka").strftime("%d %b %Y, %H:%M:%S")
    else:
        result["expiry_time_utc"] = None
        result["expiry_time_bd"] = None
    result["entry_timeframe"] = "১-মিনিট closed-candle analysis; ৫ মিনিট expiry"
    return result
