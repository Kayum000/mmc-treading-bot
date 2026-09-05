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


def strong_level_rejection(df: pd.DataFrame, lookback: int = 20) -> str:
    """Detect strong rejection from a nearby key support/resistance level.

    The level is derived only from candles before the latest closed candle.
    A SELL rejection needs the latest high to test/sweep a prior resistance
    cluster and then close decisively back below it with a meaningful upper
    wick. BUY is the inverse at support. This is an additional MMC confirmation,
    not a replacement for BOS/sweep/EMA logic.

    Importantly, rejection alone is not enough to create a trade. The latest
    rejection candle must also have an existing MMC momentum confirmation:
    either a liquidity sweep or displacement in the same direction.
    """
    if len(df) < max(lookback + 2, 8):
        return "none"

    prior = df.iloc[-lookback-1:-1].copy()
    last = df.iloc[-1]
    avg_range = float((prior["high"] - prior["low"]).tail(min(10, len(prior))).mean())
    if avg_range <= 0:
        return "none"

    tolerance = max(avg_range * 0.20, 1e-12)
    resistance = float(prior["high"].max())
    support = float(prior["low"].min())

    last_high = float(last["high"])
    last_low = float(last["low"])
    last_open = float(last["open"])
    last_close = float(last["close"])
    candle_range = max(last_high - last_low, 1e-12)
    body = abs(last_close - last_open)
    upper_wick = last_high - max(last_open, last_close)
    lower_wick = min(last_open, last_close) - last_low

    # Count nearby prior touches. Two or more touches make the level stronger
    # than a single isolated extreme without requiring volume data.
    resistance_touches = int(((prior["high"] - resistance).abs() <= tolerance).sum())
    support_touches = int(((prior["low"] - support).abs() <= tolerance).sum())

    bearish_rejection = (
        resistance_touches >= 2
        and last_high >= resistance - tolerance
        and last_close < resistance
        and upper_wick >= max(body * 1.20, candle_range * 0.25)
        and last_close <= last_low + candle_range * 0.45
    )
    bullish_rejection = (
        support_touches >= 2
        and last_low <= support + tolerance
        and last_close > support
        and lower_wick >= max(body * 1.20, candle_range * 0.25)
        and last_close >= last_low + candle_range * 0.55
    )

    # Do not let a level rejection become a standalone signal. Require one of
    # the already-existing MMC confirmations on this same closed candle.
    bearish_confirmation = (
        liquidity_sweep(df, min(10, len(df) - 1)) == "sell_side_rejection"
        or displacement(df) == "bearish"
    )
    bullish_confirmation = (
        liquidity_sweep(df, min(10, len(df) - 1)) == "buy_side_rejection"
        or displacement(df) == "bullish"
    )

    if bearish_rejection and bearish_confirmation and not bullish_rejection:
        return "strong_resistance_rejection"
    if bullish_rejection and bullish_confirmation and not bearish_rejection:
        return "strong_support_rejection"
    return "none"


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
