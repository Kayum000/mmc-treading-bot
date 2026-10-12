"""Conservative candle-based MMC + indicator hybrid signal engine.

The 22 concepts are heuristic OHLC proxies, not institutional order-flow data.
Only closed candles should be passed by the caller. Scores are vote scores, not
probabilities or guaranteed win rates.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from strategy.indicator_engine import analyze_timeframes


CONCEPTS = [
    "Market Structure", "BOS", "CHOCH", "MSS", "Buy-Side Liquidity",
    "Sell-Side Liquidity", "Liquidity Sweep", "Equal Highs", "Equal Lows",
    "Swing High/Low", "Displacement", "Fair Value Gap", "Order Block",
    "OB Mitigation", "Breaker Block", "Rejection Candle", "Retest Confirmation",
    "Premium Zone", "Discount Zone", "Equilibrium", "Higher-Timeframe Bias",
    "Candle Momentum",
]


@dataclass
class HybridSignal:
    action: str
    confidence: float
    reason: str
    regime: str
    strategy: str
    mmc_analysis: dict


def _clean(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    if candles is None or candles.empty or not required.issubset(candles.columns):
        return pd.DataFrame(columns=sorted(required))
    x = candles.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        x[col] = pd.to_numeric(x[col], errors="coerce")
    return x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


def _concept_votes(x: pd.DataFrame, tf: dict) -> dict:
    names = CONCEPTS
    votes = {name: "NEUTRAL" for name in names}
    if len(x) < 30:
        return votes
    recent = x.iloc[-30:].reset_index(drop=True)
    last = recent.iloc[-1]
    prev = recent.iloc[-2]
    close, op, high, low = map(float, (last.close, last.open, last.high, last.low))
    candle_range = max(high-low, 1e-12)
    body = abs(close-op)
    bullish = close > op
    bearish = close < op
    prior = recent.iloc[-21:-1]
    prior_high, prior_low = float(prior.high.max()), float(prior.low.min())
    prior_mid = (prior_high + prior_low) / 2
    # Local swing references use past candles only (excluding the signal candle).
    swing_hi = float(recent.high.iloc[-7:-1].max())
    swing_lo = float(recent.low.iloc[-7:-1].min())
    older_hi = float(recent.high.iloc[-13:-7].max())
    older_lo = float(recent.low.iloc[-13:-7].min())
    atr = float((recent.high-recent.low).rolling(14).mean().iloc[-2]) if len(recent) >= 15 else candle_range
    atr = max(atr if np.isfinite(atr) else candle_range, 1e-12)
    upper_wick = high - max(close, op)
    lower_wick = min(close, op) - low

    if swing_hi > older_hi and swing_lo > older_lo: votes["Market Structure"] = "BUY"
    elif swing_hi < older_hi and swing_lo < older_lo: votes["Market Structure"] = "SELL"
    if close > swing_hi: votes["BOS"] = "BUY"
    elif close < swing_lo: votes["BOS"] = "SELL"
    if older_lo < float(recent.low.iloc[-7]) and close > swing_hi: votes["CHOCH"] = "BUY"
    elif older_hi > float(recent.high.iloc[-7]) and close < swing_lo: votes["CHOCH"] = "SELL"
    if close > swing_hi and body >= 0.55*candle_range: votes["MSS"] = "BUY"
    elif close < swing_lo and body >= 0.55*candle_range: votes["MSS"] = "SELL"

    # Liquidity pools and sweeps.
    equal_high = abs(float(recent.high.iloc[-10:-1].max()) - float(recent.high.iloc[-10:-1].min())) <= atr*0.18
    equal_low = abs(float(recent.low.iloc[-10:-1].max()) - float(recent.low.iloc[-10:-1].min())) <= atr*0.18
    if equal_high: votes["Equal Highs"] = "SELL"
    if equal_low: votes["Equal Lows"] = "BUY"
    if high > swing_hi and close < swing_hi: votes["Buy-Side Liquidity"] = "SELL"
    elif low < swing_lo and close > swing_lo: votes["Sell-Side Liquidity"] = "BUY"
    if (high > swing_hi and close < swing_hi and upper_wick > body) : votes["Liquidity Sweep"] = "SELL"
    elif low < swing_lo and close > swing_lo and lower_wick > body: votes["Liquidity Sweep"] = "BUY"
    if upper_wick > body*1.5 and upper_wick > candle_range*0.35: votes["Swing High/Low"] = "SELL"
    elif lower_wick > body*1.5 and lower_wick > candle_range*0.35: votes["Swing High/Low"] = "BUY"

    if body >= atr*0.9 and bullish: votes["Displacement"] = "BUY"
    elif body >= atr*0.9 and bearish: votes["Displacement"] = "SELL"
    # Three-candle FVG proxy: gap between candle 1 and candle 3.
    c1, c3 = recent.iloc[-3], recent.iloc[-1]
    if float(c1.high) < float(c3.low): votes["Fair Value Gap"] = "BUY"
    elif float(c1.low) > float(c3.high): votes["Fair Value Gap"] = "SELL"
    # OB proxy: last opposing candle before current displacement.
    previous = recent.iloc[-5:-1]
    bull_ob = previous[(previous.close < previous.open)]
    bear_ob = previous[(previous.close > previous.open)]
    if bullish and body >= atr*0.65 and not bull_ob.empty: votes["Order Block"] = "BUY"
    elif bearish and body >= atr*0.65 and not bear_ob.empty: votes["Order Block"] = "SELL"
    # Mitigation/retest proxies require price to revisit the prior swing area.
    if low <= swing_hi and close > swing_hi and bullish: votes["OB Mitigation"] = "BUY"
    elif high >= swing_lo and close < swing_lo and bearish: votes["OB Mitigation"] = "SELL"
    if close > prior_high and float(prev.close) < prior_high: votes["Breaker Block"] = "BUY"
    elif close < prior_low and float(prev.close) > prior_low: votes["Breaker Block"] = "SELL"
    if lower_wick > candle_range*0.45 and bullish: votes["Rejection Candle"] = "BUY"
    elif upper_wick > candle_range*0.45 and bearish: votes["Rejection Candle"] = "SELL"
    if abs(close-swing_hi) <= atr*0.2 and bullish: votes["Retest Confirmation"] = "BUY"
    elif abs(close-swing_lo) <= atr*0.2 and bearish: votes["Retest Confirmation"] = "SELL"
    if close > prior_mid + atr*0.1: votes["Premium Zone"] = "SELL"
    elif close < prior_mid - atr*0.1: votes["Discount Zone"] = "BUY"
    if close > prior_mid + atr*0.05: votes["Equilibrium"] = "BUY"
    elif close < prior_mid - atr*0.05: votes["Equilibrium"] = "SELL"

    higher = [tf.get(k, {}) for k in ("5m", "15m")]
    usable = [item.get("signal") for item in higher if item.get("available") and item.get("signal") in ("BUY", "SELL")]
    if usable:
        buys, sells = usable.count("BUY"), usable.count("SELL")
        if buys > sells: votes["Higher-Timeframe Bias"] = "BUY"
        elif sells > buys: votes["Higher-Timeframe Bias"] = "SELL"
    if bullish and close > float(prev.close): votes["Candle Momentum"] = "BUY"
    elif bearish and close < float(prev.close): votes["Candle Momentum"] = "SELL"
    return votes


def generate_hybrid_signal(candles: pd.DataFrame, ticks: pd.DataFrame | None = None) -> HybridSignal:
    x = _clean(candles)
    if len(x) < 60:
        analysis = {"available": False, "reason": "কমপক্ষে ৬০টি বন্ধ 1m candle দরকার",
                    "concepts": {name: "N/A" for name in CONCEPTS}, "buy_votes": 0,
                    "sell_votes": 0, "neutral_votes": len(CONCEPTS), "score": 0}
        return HybridSignal("HOLD", 0.0, "insufficient candle history for hybrid MMC", "UNKNOWN", "MMC_HYBRID", analysis)

    timeframes = analyze_timeframes(x)
    votes = _concept_votes(x, timeframes)
    buy = sum(v == "BUY" for v in votes.values())
    sell = sum(v == "SELL" for v in votes.values())
    neutral = len(votes)-buy-sell
    score = int(round(100*(buy-sell)/max(1, buy+sell)))
    indicator = timeframes.get("1m", {})
    ind_signal = indicator.get("signal", "WAIT")
    higher = [timeframes.get(k, {}) for k in ("5m", "15m")]
    opposing_higher = all(t.get("available") and t.get("signal") in ("BUY", "SELL") and t.get("signal") != ("BUY" if buy > sell else "SELL") for t in higher)
    action = "HOLD"
    reason = "MMC confirmation not strong enough; WAIT"
    direction = "BUY" if buy > sell else "SELL" if sell > buy else "WAIT"
    # Balanced mode: >=7 directional concept votes, gap >=2, and no strong
    # 1m-indicator or complete higher-timeframe disagreement.
    if direction in ("BUY", "SELL") and max(buy, sell) >= 7 and abs(buy-sell) >= 2:
        if ind_signal in ("BUY", "SELL") and ind_signal != direction:
            reason = f"MMC {direction} but 1m indicator vote opposes; WAIT"
        elif opposing_higher:
            reason = f"MMC {direction} but both 5m and 15m oppose; WAIT"
        else:
            action = direction
            reason = f"MMC {direction}: {max(buy,sell)}/22 directional votes; indicator/timeframe checks passed"
    confidence = min(0.82, 0.50 + 0.025*max(0, abs(buy-sell)-1)) if action in ("BUY", "SELL") else 0.0
    # Confidence is a rule-strength score only, not a calibrated win probability.
    analysis = {
        "available": True, "concept_count": len(CONCEPTS), "concepts": votes,
        "buy_votes": buy, "sell_votes": sell, "neutral_votes": neutral,
        "score": score, "direction": direction, "indicator_signal": ind_signal,
        "timeframe_signals": {k: {"available": v.get("available", False), "signal": v.get("signal", "WAIT")} for k, v in timeframes.items()},
        "note": "MMC conceptগুলো OHLC-ভিত্তিক heuristic proxy; vote score/confidence জয়ের সম্ভাবনা নয়।",
    }
    regime = "MMC_BULLISH" if action == "BUY" else "MMC_BEARISH" if action == "SELL" else "MMC_WAIT"
    return HybridSignal(action, confidence, reason, regime, "MMC_HYBRID_BALANCED", analysis)
