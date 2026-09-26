"""Candle-reaction strategy for Real and Quotex OTC markets.

This is an independent strategy mode. It uses only the latest fully closed
candle plus historical candles available before it; it never replaces the
existing adaptive strategy.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class CandleReactionSignal:
    action: str
    confidence: float
    reason: str
    regime: str = "CANDLE_REACTION"
    strategy: str = "CANDLE_REACTION"


def _prepare(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(candles.columns)
    if missing:
        raise ValueError(f"missing candle columns: {sorted(missing)}")
    x = candles.copy()
    for c in ("open", "high", "low", "close"):
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    return x.reset_index(drop=True)


def _near(level: float, price: float, tolerance: float) -> bool:
    return abs(price - level) <= tolerance


def generate_candle_reaction_signal(candles: pd.DataFrame) -> CandleReactionSignal:
    """Generate a closed-candle support/resistance reaction signal.

    BUY requires a bullish rejection from recent support/demand.
    SELL requires a bearish rejection from recent resistance/supply.
    Engulfing is accepted as an additional reaction pattern when it agrees
    with the same support/resistance context.
    """
    x = _prepare(candles)
    if len(x) < 22:
        return CandleReactionSignal("HOLD", 0.0, "পর্যাপ্ত candle history নেই")

    cur = x.iloc[-1]
    prev = x.iloc[-2]

    o, h, l, c = map(float, (cur["open"], cur["high"], cur["low"], cur["close"]))
    po, ph, pl, pc = map(float, (prev["open"], prev["high"], prev["low"], prev["close"]))
    candle_range = h - l
    if candle_range <= 0:
        return CandleReactionSignal("HOLD", 0.0, "বর্তমান candle-এ কার্যকর range নেই")

    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    body_ratio = body / candle_range
    close_position = (c - l) / candle_range

    history = x.iloc[:-1]
    support = float(history["low"].tail(20).min())
    resistance = float(history["high"].tail(20).max())

    ranges = (history["high"] - history["low"]).tail(20)
    atr = float(ranges.mean()) if not ranges.empty else candle_range
    tolerance = max(atr * 0.30, candle_range * 0.15)

    at_support = _near(l, support, tolerance) or _near(c, support, tolerance)
    at_resistance = _near(h, resistance, tolerance) or _near(c, resistance, tolerance)

    bullish_engulf = (
        pc < po and c > o and o <= pc and c >= po and body >= abs(pc - po)
    )
    bearish_engulf = (
        pc > po and c < o and o >= pc and c <= po and body >= abs(pc - po)
    )

    bullish_rejection = (
        c > o
        and lower_wick >= max(body * 1.20, candle_range * 0.20)
        and close_position >= 0.65
        and body_ratio >= 0.20
    )
    bearish_rejection = (
        c < o
        and upper_wick >= max(body * 1.20, candle_range * 0.20)
        and close_position <= 0.35
        and body_ratio >= 0.20
    )

    buy_reaction = at_support and (bullish_rejection or bullish_engulf)
    sell_reaction = at_resistance and (bearish_rejection or bearish_engulf)

    if buy_reaction and not sell_reaction:
        score = 62
        reasons = ["সাপোর্টে candle reaction"]
        if bullish_rejection:
            score += 16
            reasons.append("নিচের wick rejection")
        if bullish_engulf:
            score += 12
            reasons.append("বুলিশ engulfing")
        if close_position >= 0.80:
            score += 5
            reasons.append("শক্তিশালী বুলিশ close")
        score = min(score, 95)
        return CandleReactionSignal("BUY", score / 100.0, " • ".join(reasons))

    if sell_reaction and not buy_reaction:
        score = 62
        reasons = ["রেজিস্ট্যান্সে candle reaction"]
        if bearish_rejection:
            score += 16
            reasons.append("উপরের wick rejection")
        if bearish_engulf:
            score += 12
            reasons.append("বিয়ারিশ engulfing")
        if close_position <= 0.20:
            score += 5
            reasons.append("শক্তিশালী বিয়ারিশ close")
        score = min(score, 95)
        return CandleReactionSignal("SELL", score / 100.0, " • ".join(reasons))

    if at_support and at_resistance:
        return CandleReactionSignal("HOLD", 0.0, "support ও resistance একই candle-এ overlap করেছে")
    if at_support:
        return CandleReactionSignal("HOLD", 0.0, "support-এ candle reaction confirmation পাওয়া যায়নি")
    if at_resistance:
        return CandleReactionSignal("HOLD", 0.0, "resistance-এ candle reaction confirmation পাওয়া যায়নি")
    return CandleReactionSignal("HOLD", 0.0, "গুরুত্বপূর্ণ support/resistance-এ candle reaction পাওয়া যায়নি")
