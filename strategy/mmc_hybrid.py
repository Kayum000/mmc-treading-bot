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
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    # Reject malformed bars so bad quotes cannot become structure or liquidity votes.
    finite = np.isfinite(x[["open", "high", "low", "close"]].to_numpy(dtype=float)).all(axis=1)
    valid = (
        finite
        & (x["open"] > 0) & (x["high"] > 0) & (x["low"] > 0) & (x["close"] > 0)
        & (x["high"] >= x[["open", "close", "low"]].max(axis=1))
        & (x["low"] <= x[["open", "close", "high"]].min(axis=1))
    )
    return x.loc[valid].reset_index(drop=True)


def _concept_votes(x: pd.DataFrame, tf: dict) -> dict:
    """Evaluate 22 transparent OHLC rules using completed candles only.

    These are reproducible price-action proxies. OHLC alone cannot confirm
    actual resting liquidity, institutional order flow, or subjective OB validity.
    """
    votes = {name: "NEUTRAL" for name in CONCEPTS}
    if len(x) < 60:
        return votes

    # Use prior candles to establish reference levels; the latest candle is
    # evaluated as the signal candle. Pivot candidates need candles on both sides.
    d = x.reset_index(drop=True)
    last_i = len(d) - 1
    last = d.iloc[last_i]
    prev = d.iloc[last_i - 1]
    close, op, high, low = (float(last[k]) for k in ("close", "open", "high", "low"))
    candle_range = max(high - low, 1e-12)
    body = abs(close - op)
    bullish, bearish = close > op, close < op
    upper_wick = high - max(close, op)
    lower_wick = min(close, op) - low

    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift(1)).abs(),
        (d["low"] - d["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_series = tr.rolling(14).mean()
    atr = float(atr_series.iloc[-2]) if pd.notna(atr_series.iloc[-2]) else candle_range
    atr = max(atr, 1e-12)

    # Confirmed swing pivots: the pivot is at least two bars old, so no
    # future candle is used to decide the signal candle's direction.
    pivot_window = d.iloc[max(0, last_i - 40):last_i - 1].copy()
    swing_highs, swing_lows = [], []
    for i in range(2, len(pivot_window) - 2):
        row = pivot_window.iloc[i]
        h0, l0 = float(row.high), float(row.low)
        if h0 >= float(pivot_window.high.iloc[i-2:i+3].max()):
            swing_highs.append((pivot_window.index[i], h0))
        if l0 <= float(pivot_window.low.iloc[i-2:i+3].min()):
            swing_lows.append((pivot_window.index[i], l0))
    recent_highs = [p for p in swing_highs if p[0] >= last_i - 25]
    recent_lows = [p for p in swing_lows if p[0] >= last_i - 25]
    swing_hi = recent_highs[-1][1] if recent_highs else float(d.high.iloc[-21:-1].max())
    swing_lo = recent_lows[-1][1] if recent_lows else float(d.low.iloc[-21:-1].min())
    prior_high = float(d.high.iloc[-21:-1].max())
    prior_low = float(d.low.iloc[-21:-1].min())
    prior_mid = (prior_high + prior_low) / 2.0

    # Market structure uses the sequence of the two latest confirmed swing points.
    if len(recent_highs) >= 2 and len(recent_lows) >= 2:
        hh = recent_highs[-1][1] > recent_highs[-2][1]
        hl = recent_lows[-1][1] > recent_lows[-2][1]
        lh = recent_highs[-1][1] < recent_highs[-2][1]
        ll = recent_lows[-1][1] < recent_lows[-2][1]
        if hh and hl:
            votes["Market Structure"] = "BUY"
        elif lh and ll:
            votes["Market Structure"] = "SELL"

    # BOS = close through the latest confirmed swing in the existing structure.
    broke_up, broke_down = close > swing_hi, close < swing_lo
    if broke_up:
        votes["BOS"] = "BUY"
    elif broke_down:
        votes["BOS"] = "SELL"

    # CHOCH/MSS only vote when a close breaks the opposite-side swing against
    # the prior confirmed structure; MSS additionally requires displacement.
    prior_structure = votes["Market Structure"]
    if prior_structure == "SELL" and broke_up:
        votes["CHOCH"] = "BUY"
    elif prior_structure == "BUY" and broke_down:
        votes["CHOCH"] = "SELL"
    if body >= 0.8 * atr and candle_range > 0 and body / candle_range >= 0.60:
        if broke_up and bullish:
            votes["MSS"] = "BUY"
        elif broke_down and bearish:
            votes["MSS"] = "SELL"

    # Equal highs/lows require at least two distinct swing points close in price.
    tol = max(0.12 * atr, abs(close) * 0.00002)
    eqh = len(recent_highs) >= 2 and abs(recent_highs[-1][1] - recent_highs[-2][1]) <= tol
    eql = len(recent_lows) >= 2 and abs(recent_lows[-1][1] - recent_lows[-2][1]) <= tol
    if eqh:
        votes["Equal Highs"] = "DETECTED"  # liquidity pool exists; no direction until sweep/reclaim
    if eql:
        votes["Equal Lows"] = "DETECTED"

    # Sweep requires piercing a prior level and closing back inside it.
    sweep_bsl = high > swing_hi and close < swing_hi
    sweep_ssl = low < swing_lo and close > swing_lo
    if sweep_bsl:
        votes["Buy-Side Liquidity"] = "SELL"
        votes["Liquidity Sweep"] = "SELL"
    elif sweep_ssl:
        votes["Sell-Side Liquidity"] = "BUY"
        votes["Liquidity Sweep"] = "BUY"

    # Candle rejection/swing reaction; do not count a neutral doji as directional.
    if bullish and lower_wick >= max(body * 1.5, candle_range * 0.35):
        votes["Swing High/Low"] = "BUY"
        votes["Rejection Candle"] = "BUY"
    elif bearish and upper_wick >= max(body * 1.5, candle_range * 0.35):
        votes["Swing High/Low"] = "SELL"
        votes["Rejection Candle"] = "SELL"

    # Displacement: body materially larger than recent ATR and close near candle extreme.
    if bullish and body >= 1.0 * atr and (high - close) <= 0.20 * candle_range:
        votes["Displacement"] = "BUY"
    elif bearish and body >= 1.0 * atr and (close - low) <= 0.20 * candle_range:
        votes["Displacement"] = "SELL"

    # Three-candle FVG definition: candle 1 high below candle 3 low, or vice versa.
    c1, c3 = d.iloc[-3], d.iloc[-1]
    bull_fvg = float(c1.high) < float(c3.low)
    bear_fvg = float(c1.low) > float(c3.high)
    if bull_fvg:
        votes["Fair Value Gap"] = "BUY"
    elif bear_fvg:
        votes["Fair Value Gap"] = "SELL"

    # Order-block proxy is derived from a completed earlier displacement,
    # then the current candle is checked separately for a zone revisit.
    ob = None
    ob_dir = None
    search_start = max(10, last_i - 8)
    for j in range(last_i - 1, search_start - 1, -1):
        disp = d.iloc[j]
        disp_body = abs(float(disp.close) - float(disp.open))
        disp_range = max(float(disp.high) - float(disp.low), 1e-12)
        if disp_body < atr * 0.8 or disp_body / disp_range < 0.60:
            continue
        # Require a close beyond a swing level known before that displacement.
        ref = d.iloc[max(0, j - 20):j]
        if ref.empty:
            continue
        ref_high, ref_low = float(ref.high.max()), float(ref.low.min())
        if float(disp.close) > ref_high and float(disp.close) > float(disp.open):
            opposing = d.iloc[max(0, j - 5):j]
            opposing = opposing[opposing.close < opposing.open]
            if not opposing.empty:
                ob, ob_dir = opposing.iloc[-1], "BUY"
                break
        if float(disp.close) < ref_low and float(disp.close) < float(disp.open):
            opposing = d.iloc[max(0, j - 5):j]
            opposing = opposing[opposing.close > opposing.open]
            if not opposing.empty:
                ob, ob_dir = opposing.iloc[-1], "SELL"
                break
    if ob is not None:
        ob_high, ob_low = float(ob.high), float(ob.low)
        votes["Order Block"] = ob_dir
        # Mitigation only counts when the current candle revisits the already
        # formed zone and closes back outside it in the original direction.
        if ob_dir == "BUY" and low <= ob_high and close > ob_high and bullish:
            votes["OB Mitigation"] = "BUY"
        elif ob_dir == "SELL" and high >= ob_low and close < ob_low and bearish:
            votes["OB Mitigation"] = "SELL"

    # Breaker proxy: prior range boundary breaks and the immediately prior close
    # was on the other side; this is a level-flip approximation, not order-flow.
    if close > prior_high and float(prev.close) <= prior_high:
        votes["Breaker Block"] = "BUY"
    elif close < prior_low and float(prev.close) >= prior_low:
        votes["Breaker Block"] = "SELL"

    # Retest is only counted when an earlier close broke the level, and current
    # candle revisits it and closes back on the breakout side.
    hist = d.iloc[-6:-1]
    prior_bull_break = bool((hist.close > swing_hi).any())
    prior_bear_break = bool((hist.close < swing_lo).any())
    if prior_bull_break and low <= swing_hi + 0.15 * atr and close > swing_hi and bullish:
        votes["Retest Confirmation"] = "BUY"
    elif prior_bear_break and high >= swing_lo - 0.15 * atr and close < swing_lo and bearish:
        votes["Retest Confirmation"] = "SELL"

    # Premium/discount are location labels, not directional signals on their own.
    # Vote only when price is in the relevant half AND a matching reaction exists.
    if close > prior_mid:
        votes["Premium Zone"] = "SELL" if sweep_bsl and bearish else "DETECTED"
    elif close < prior_mid:
        votes["Discount Zone"] = "BUY" if sweep_ssl and bullish else "DETECTED"
    if abs(close - prior_mid) <= 0.10 * atr:
        votes["Equilibrium"] = "DETECTED"

    higher = [tf.get(k, {}) for k in ("5m", "15m")]
    usable = [item.get("signal") for item in higher
              if item.get("available") and item.get("signal") in ("BUY", "SELL")]
    if len(usable) == 2 and usable[0] == usable[1]:
        votes["Higher-Timeframe Bias"] = usable[0]

    if bullish and close > float(prev.close) and body >= 0.25 * atr:
        votes["Candle Momentum"] = "BUY"
    elif bearish and close < float(prev.close) and body >= 0.25 * atr:
        votes["Candle Momentum"] = "SELL"
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
    detected = sum(v == "DETECTED" for v in votes.values())
    neutral = sum(v == "NEUTRAL" for v in votes.values())
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
        "buy_votes": buy, "sell_votes": sell, "detected_concepts": detected, "neutral_votes": neutral,
        "score": score, "direction": direction, "indicator_signal": ind_signal,
        "timeframe_signals": {k: {"available": v.get("available", False), "signal": v.get("signal", "WAIT")} for k, v in timeframes.items()},
        "note": "MMC conceptগুলো OHLC-ভিত্তিক heuristic proxy; vote score/confidence জয়ের সম্ভাবনা নয়।",
    }
    regime = "MMC_BULLISH" if action == "BUY" else "MMC_BEARISH" if action == "SELL" else "MMC_WAIT"
    return HybridSignal(action, confidence, reason, regime, "MMC_HYBRID_BALANCED", analysis)
