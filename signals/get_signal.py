"""Signal generation for Real Forex and Quotex OTC markets."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from data.biquote_forex import fetch_tick_history
from data.quotex_otc import fetch_quotex_candles, OTC_PAIRS, local_active_asset
from data.otc_markets import display_for_asset, asset_for_display
from strategy.tick_run_pressure import generate_signal as generate_forex_signal
from strategy.otc_candle_pressure import generate_signal as generate_otc_signal


def _bengali_reason(reason: str) -> str:
    """Return a user-facing Bengali explanation without changing strategy logic."""
    text = str(reason or "").strip()
    exact = {
        "Bullish multi-timeframe MMC confirmation": "বুলিশ মাল্টি-টাইমফ্রেম MMC কনফার্মেশন পাওয়া গেছে।",
        "Bearish multi-timeframe MMC confirmation": "বিয়ারিশ মাল্টি-টাইমফ্রেম MMC কনফার্মেশন পাওয়া গেছে।",
        "Insufficient or conflicting confirmation": "যথেষ্ট কনফার্মেশন পাওয়া যায়নি অথবা কনফার্মেশনগুলোর মধ্যে অসামঞ্জস্য রয়েছে।",
        "insufficient tick history": "যথেষ্ট টিক ডাটা পাওয়া যায়নি।",
        "run confirmation absent": "প্রয়োজনীয় প্রাইস-রান কনফার্মেশন পাওয়া যায়নি।",
        "quote pressure unavailable": "কোট-প্রেশার ডাটা পাওয়া যাচ্ছে না।",
        "run and pressure are not aligned": "প্রাইস-রান ও প্রেশার একই দিকে কনফার্ম করছে না।",
    }
    if text in exact:
        return exact[text]
    replacements = (
        ("spread too wide", "স্প্রেড বেশি"),
        ("upward run", "উর্ধ্বমুখী প্রাইস-রান"),
        ("downward run", "নিম্নমুখী প্রাইস-রান"),
        ("pressure", "প্রেশার"),
        ("quote-pressure fallback", "কোট-প্রেশার বিকল্প ডাটা"),
        ("volume-weighted microprice", "ভলিউম-ওয়েটেড মাইক্রোপ্রাইস"),
        ("fast tick confirmation", "দ্রুত টিক কনফার্মেশন"),
        ("BUY", "ক্রয়"),
        ("SELL", "বিক্রয়"),
        ("HOLD", "অপেক্ষা"),
        ("Bullish", "বুলিশ"),
        ("Bearish", "বিয়ারিশ"),
        ("run", "প্রাইস-রান"),
        ("tick", "টিক"),
    )
    for source, translated in replacements:
        text = text.replace(source, translated)
    return text


def _score_view(confidence) -> tuple[int, str]:
    """Expose a stable 0-100 score for the UI while preserving raw confidence."""
    try:
        score = int(round(float(confidence) * 100.0))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))
    if score >= 80:
        bucket = "STRONG"
    elif score >= 65:
        bucket = "GOOD"
    elif score > 0:
        bucket = "WEAK"
    else:
        bucket = "NO_SCORE"
    return score, bucket


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
    signal_score, score_bucket = _score_view(result.confidence)
    return {
        "pair": pair, "requested_pair": pair, "market_mode": "real", "source": "BiQuote tick history",
        "signal": result.action, "market_bias": result.action, "entry_signal": result.action,
        "buy_score": 1 if result.action == "BUY" else 0, "sell_score": 1 if result.action == "SELL" else 0,
        "signal_score": signal_score, "score": signal_score, "score_bucket": score_bucket,
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
    # Only the data source/market selection is dynamic.
    signal_at_utc = datetime.now(timezone.utc)
    candles = fetch_quotex_candles(asset, count=240)
    result = generate_otc_signal(candles)
    last = candles.iloc[-1]
    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    is_entry = result.action in {"BUY", "SELL"}
    signal_candle = signal_at_utc.replace(second=0, microsecond=0)
    signal_score, score_bucket = _score_view(result.confidence)
    return {
        "pair": pair, "requested_pair": requested_pair, "detected_asset": asset, "market_mode": "quotex_otc",
        "source": "Quotex OTC local Windows/Android screen collector", "signal": result.action, "market_bias": result.action,
        "entry_signal": result.action, "buy_score": 1 if result.action == "BUY" else 0,
        "sell_score": 1 if result.action == "SELL" else 0,
        "signal_score": signal_score, "score": signal_score, "score_bucket": score_bucket,
        "reason": _bengali_reason(result.reason),
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
