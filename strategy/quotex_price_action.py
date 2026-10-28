"""Strict 1-minute Quotex price-action strategy.

Signals are based only on completed OHLC candles. The strategy deliberately
returns HOLD when trend, location, or candle confirmation is missing. Confidence
is a rule-strength heuristic, never a calibrated win probability.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class PriceActionSignal:
    action: str
    confidence: float
    reason: str
    regime: str
    strategy: str
    mmc_analysis: dict


def _clean(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    if candles is None or not isinstance(candles, pd.DataFrame) or candles.empty:
        return pd.DataFrame(columns=sorted(required))
    if not required.issubset(candles.columns):
        return pd.DataFrame(columns=sorted(required))
    x = candles.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        x[col] = pd.to_numeric(x[col], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    values = x[["open", "high", "low", "close"]].to_numpy(dtype=float)
    valid = (
        np.isfinite(values).all(axis=1)
        & (x["open"].to_numpy() > 0)
        & (x["low"].to_numpy() > 0)
        & (x["high"].to_numpy() >= x[["open", "close", "low"]].max(axis=1).to_numpy())
        & (x["low"].to_numpy() <= x[["open", "close", "high"]].min(axis=1).to_numpy())
    )
    return x.loc[valid].reset_index(drop=True)


def _hold(reason: str, analysis: dict | None = None) -> PriceActionSignal:
    details = analysis or {}
    details.update({
        "available": bool(details.get("available", False)),
        "direction": "HOLD",
        "setup": details.get("setup", "NONE"),
        "confidence_basis": "rule_strength_not_win_probability",
        "note": reason,
    })
    return PriceActionSignal("HOLD", 0.0, reason, "NO_TRADE", "QUOTEX_PRICE_ACTION_1M", details)


def generate_quotex_price_action_signal(candles: pd.DataFrame) -> PriceActionSignal:
    """Evaluate trend + support/resistance + closed-candle confirmation.

    The caller must supply completed 1-minute candles only. This function does
    not place trades, choose stake size, or guarantee a useful expiry.
    """
    x = _clean(candles)
    if len(x) < 60:
        return _hold(
            "পর্যাপ্ত closed 1-minute candle নেই; অন্তত ৬০টি candle দরকার",
            {"candle_count": len(x), "available": False},
        )

    d = x.copy().reset_index(drop=True)
    last = d.iloc[-1]
    prior = d.iloc[-2]
    ts = pd.to_datetime(d["timestamp"], utc=True).dt.floor("min")
    d["bar_minute"] = ts
    grouped = d.set_index("bar_minute").sort_index()
    resampler = grouped.resample("5min", label="left", closed="left")
    counts = resampler["close"].count()
    m5 = resampler.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    m5 = m5.loc[counts.reindex(m5.index).fillna(0).eq(5)].dropna(subset=["close"])
    if len(m5) < 21:
        return _hold(
            "৫-মিনিটের Trend যাচাই করার মতো সম্পূর্ণ history নেই",
            {"candle_count": len(x), "m5_candles": len(m5), "available": False},
        )

    ema9 = m5["close"].ewm(span=9, adjust=False).mean()
    ema21 = m5["close"].ewm(span=21, adjust=False).mean()
    if ema9.iloc[-1] > ema21.iloc[-1] and m5["close"].iloc[-1] >= m5["close"].iloc[-2]:
        trend = "BUY"
    elif ema9.iloc[-1] < ema21.iloc[-1] and m5["close"].iloc[-1] <= m5["close"].iloc[-2]:
        trend = "SELL"
    else:
        return _hold("৫-মিনিটের Trend পরিষ্কার নয়; ট্রেড বাদ", {
            "available": True, "trend": "NEUTRAL", "m5_candles": len(m5),
        })

    # Require the latest fully formed M5 candle itself to confirm the EMA trend.
    # This is stricter than EMA alignment alone: an opposing or doji M5 bar means HOLD.
    latest_m5 = m5.iloc[-1]
    m5_bullish = float(latest_m5["close"]) > float(latest_m5["open"])
    m5_bearish = float(latest_m5["close"]) < float(latest_m5["open"])
    if (trend == "BUY" and not m5_bullish) or (trend == "SELL" and not m5_bearish):
        return _hold("শেষ সম্পূর্ণ ৫-মিনিট candle-এর দিক Trend-এর সঙ্গে মেলেনি; ট্রেড বাদ", {
            "available": True, "trend": trend, "m5_candles": len(m5),
            "m5_confirmation": "OPPOSING_OR_DOJI",
            "m5_last_open": float(latest_m5["open"]),
            "m5_last_close": float(latest_m5["close"]),
        })

    d["tr"] = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift(1)).abs(),
        (d["low"] - d["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_series = d["tr"].rolling(14).mean()
    atr = float(atr_series.iloc[-2])
    if not np.isfinite(atr) or atr <= 0:
        return _hold("ATR/price range নির্ভরযোগ্য নয়; ট্রেড বাদ", {"available": True, "trend": trend})

    # Recent 20 bars define reference levels; the signal candle is excluded.
    lookback = d.iloc[-21:-1]
    resistance = float(lookback["high"].max())
    support = float(lookback["low"].min())
    op, high, low, close = (float(last[k]) for k in ("open", "high", "low", "close"))
    body = abs(close - op)
    candle_range = max(high - low, 1e-12)
    upper_wick = high - max(op, close)
    lower_wick = min(op, close) - low
    bullish = close > op
    bearish = close < op
    close_position = (close - low) / candle_range

    # Reject doji/small-body candles; wait for a decisive close.
    if body < 0.20 * atr or candle_range < 0.25 * atr:
        return _hold("Confirmation candle দুর্বল/Doji; পরের সেটআপের জন্য অপেক্ষা", {
            "available": True, "trend": trend, "support": support, "resistance": resistance,
            "atr": atr, "setup": "WEAK_CANDLE",
        })

    # Rejection at the range edge, or a break-and-retest of a prior range.
    near_support = low <= support + 0.15 * atr and close > support
    near_resistance = high >= resistance - 0.15 * atr and close < resistance
    bullish_rejection = near_support and bullish and lower_wick >= max(1.2 * body, 0.25 * candle_range) and close_position >= 0.65
    bearish_rejection = near_resistance and bearish and upper_wick >= max(1.2 * body, 0.25 * candle_range) and close_position <= 0.35

    # Range before the most recent five candles, so a prior close can establish
    # the break and the current candle can retest it without look-ahead.
    base = d.iloc[-26:-6]
    prior_breaks = d.iloc[-6:-1]
    base_high = float(base["high"].max())
    base_low = float(base["low"].min())
    bullish_retest = (
        bool((prior_breaks["close"] > base_high).any())
        and low <= base_high + 0.15 * atr and close > base_high and bullish and close_position >= 0.65
    )
    bearish_retest = (
        bool((prior_breaks["close"] < base_low).any())
        and high >= base_low - 0.15 * atr and close < base_low and bearish and close_position <= 0.35
    )

    buy_setup = bullish_rejection or bullish_retest
    sell_setup = bearish_rejection or bearish_retest
    if buy_setup and sell_setup:
        return _hold("একই candle-এ পরস্পরবিরোধী setup; ট্রেড বাদ", {
            "available": True, "trend": trend, "support": support, "resistance": resistance,
            "setup": "CONFLICT",
        })

    if trend == "BUY" and buy_setup:
        action = "BUY"
        setup = "SUPPORT_REJECTION" if bullish_rejection else "BREAKOUT_RETEST"
        invalidation = support if bullish_rejection else base_high
        confirmation = "Bullish close + support rejection/retest; M5 trend aligned"
    elif trend == "SELL" and sell_setup:
        action = "SELL"
        setup = "RESISTANCE_REJECTION" if bearish_rejection else "BREAKDOWN_RETEST"
        invalidation = resistance if bearish_rejection else base_low
        confirmation = "Bearish close + resistance rejection/retest; M5 trend aligned"
    else:
        return _hold("Trend, level ও candle confirmation একদিকে মেলেনি; ট্রেড বাদ", {
            "available": True, "trend": trend, "support": support, "resistance": resistance,
            "setup": "NO_CONFLUENCE", "buy_setup": buy_setup, "sell_setup": sell_setup,
        })

    # A confirmation is invalid if price already closed through its level.
    if action == "BUY" and close <= float(invalidation):
        return _hold("দাম invalidation level-এর নিচে/সমান close করেছে", {
            "available": True, "trend": trend, "support": support, "resistance": resistance,
            "setup": "INVALIDATED",
        })
    if action == "SELL" and close >= float(invalidation):
        return _hold("দাম invalidation level-এর ওপরে/সমান close করেছে", {
            "available": True, "trend": trend, "support": support, "resistance": resistance,
            "setup": "INVALIDATED",
        })

    strength = min(0.78, 0.50 + (body / atr - 0.20) * 0.08)
    if (bullish_rejection if action == "BUY" else bearish_rejection):
        strength += 0.05
    confidence = round(min(0.78, max(0.50, strength)), 2)
    reason = f"{action}: {confirmation}. Confidence = rule strength, not win probability."
    analysis = {
        "available": True,
        "direction": action,
        "trend": trend,
        "setup": setup,
        "confirmation": confirmation,
        "support": support,
        "resistance": resistance,
        "invalidation_level": float(invalidation),
        "atr": atr,
        "candle_count": len(d),
        "m5_candles": len(m5),
        "confidence_basis": "rule_strength_not_win_probability",
        "expiry_guidance": "১ ও ২ মিনিট expiry Demo-তে আলাদা করে পরীক্ষা করো; কোনোটিই নিশ্চিতভাবে ভালো নয়",
        "risk_note": "Binary Options-এ হারলে Stake-এর পুরোটা হারানোর ঝুঁকি থাকে; signal লাভের নিশ্চয়তা নয়",
    }
    regime = "PA_BULLISH" if action == "BUY" else "PA_BEARISH"
    return PriceActionSignal(action, confidence, reason, regime, "QUOTEX_PRICE_ACTION_1M", analysis)
