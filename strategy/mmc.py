import pandas as pd


def _last(df: pd.DataFrame, column: str):
    return df[column].iloc[-1] if column in df and not df.empty else None


def market_structure(df: pd.DataFrame, lookback: int = 3) -> str:
    """Simple BOS-style structure state from recent closes/highs/lows.
    This is a rule-based approximation, not a claim of institutional order flow.
    """
    if len(df) < lookback + 2:
        return "neutral"
    recent = df.tail(lookback + 1)
    prev_high = recent["high"].iloc[:-1].max()
    prev_low = recent["low"].iloc[:-1].min()
    close = recent["close"].iloc[-1]
    if close > prev_high:
        return "bullish_bos"
    if close < prev_low:
        return "bearish_bos"
    return "neutral"


def liquidity_sweep(df: pd.DataFrame, lookback: int = 10) -> str:
    """Detect a basic sweep-and-reclaim pattern on the latest candle."""
    if len(df) < lookback + 1:
        return "none"
    prior = df.iloc[-lookback-1:-1]
    last = df.iloc[-1]
    prior_high = prior["high"].max()
    prior_low = prior["low"].min()
    if last["high"] > prior_high and last["close"] < prior_high:
        return "sell_side_rejection"
    if last["low"] < prior_low and last["close"] > prior_low:
        return "buy_side_rejection"
    return "none"


def displacement(df: pd.DataFrame) -> str:
    if len(df) < 2:
        return "none"
    prev, last = df.iloc[-2], df.iloc[-1]
    prev_range = max(prev["high"] - prev["low"], 1e-12)
    body = abs(last["close"] - last["open"])
    if body < prev_range * 0.7:
        return "none"
    return "bullish" if last["close"] > last["open"] else "bearish"


def breakout_retest_role_reversal(df: pd.DataFrame, lookback: int = 10) -> str:
    """Detect breakout -> retest -> role-reversal confirmation.

    Bullish: price closes above a prior resistance level, then a later candle
    retests that level and closes back above it (resistance becomes support).
    Bearish is the inverse (support becomes resistance).

    The level is taken from the candles immediately before the breakout, and
    retest tolerance is adaptive to recent candle range so the rule works
    across different price scales without changing the existing score system.
    """
    if len(df) < lookback + 3:
        return "none"

    start = max(lookback, len(df) - (lookback * 3))
    recent = df.iloc[start:].reset_index(drop=True)
    if len(recent) < lookback + 2:
        return "none"

    avg_range = (recent["high"] - recent["low"]).tail(lookback).mean()
    tolerance = max(float(avg_range) * 0.25, 1e-12)

    # Search for the most recent breakout followed by a confirmed retest.
    for breakout_idx in range(len(recent) - 2, lookback - 1, -1):
        prior = recent.iloc[breakout_idx - lookback:breakout_idx]
        breakout = recent.iloc[breakout_idx]
        resistance = float(prior["high"].max())
        support = float(prior["low"].min())

        if float(breakout["close"]) > resistance:
            for retest_idx in range(breakout_idx + 1, len(recent)):
                retest = recent.iloc[retest_idx]
                touched = float(retest["low"]) <= resistance + tolerance
                held = float(retest["close"]) > resistance
                if touched and held:
                    return "bullish_role_reversal"

        if float(breakout["close"]) < support:
            for retest_idx in range(breakout_idx + 1, len(recent)):
                retest = recent.iloc[retest_idx]
                touched = float(retest["high"]) >= support - tolerance
                held = float(retest["close"]) < support
                if touched and held:
                    return "bearish_role_reversal"

    return "none"
