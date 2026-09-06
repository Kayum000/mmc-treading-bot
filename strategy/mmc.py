import pandas as pd


def market_structure(df: pd.DataFrame, lookback: int = 3) -> str:
    """Return the latest closed-candle BOS direction."""
    if df is None or len(df) < lookback + 2:
        return "neutral"
    prior = df.iloc[-lookback-1:-1]
    last = df.iloc[-1]
    if float(last["close"]) > float(prior["high"].max()):
        return "bullish_bos"
    if float(last["close"]) < float(prior["low"].min()):
        return "bearish_bos"
    return "neutral"


def liquidity_sweep(df: pd.DataFrame, lookback: int = 10) -> str:
    """Detect a closed-candle sweep and reclaim of a prior high/low."""
    if df is None or len(df) < lookback + 1:
        return "none"
    prior = df.iloc[-lookback-1:-1]
    last = df.iloc[-1]
    prior_high = float(prior["high"].max())
    prior_low = float(prior["low"].min())
    if float(last["high"]) > prior_high and float(last["close"]) < prior_high:
        return "sell_side_rejection"
    if float(last["low"]) < prior_low and float(last["close"]) > prior_low:
        return "buy_side_rejection"
    return "none"


def displacement(df: pd.DataFrame) -> str:
    """Detect a decisive impulse relative to the previous candle's range."""
    if df is None or len(df) < 2:
        return "none"
    prev, last = df.iloc[-2], df.iloc[-1]
    prev_range = max(float(prev["high"] - prev["low"]), 1e-12)
    body = abs(float(last["close"] - last["open"]))
    if body < prev_range * 0.70:
        return "none"
    if float(last["close"]) > float(last["open"]):
        return "bullish"
    if float(last["close"]) < float(last["open"]):
        return "bearish"
    return "none"


def _key_levels(df: pd.DataFrame, lookback: int = 20):
    prior = df.iloc[-lookback-1:-1]
    recent = prior.tail(min(10, len(prior)))
    avg_range = float((recent["high"] - recent["low"]).mean())
    tolerance = max(avg_range * 0.12, 1e-12)
    resistance = float(prior["high"].max())
    support = float(prior["low"].min())
    resistance_touches = int(((prior["high"] - resistance).abs() <= tolerance).sum())
    support_touches = int(((prior["low"] - support).abs() <= tolerance).sum())
    return resistance, support, tolerance, resistance_touches, support_touches


def strong_level_rejection(df: pd.DataFrame, lookback: int = 20) -> str:
    """Identify a clean MMC rejection at a proven support/resistance cluster.

    Resistance rejection is a SELL setup; support rejection is a BUY setup.
    Touching a level alone is never enough. The latest closed candle must show
    a meaningful wick, close away from the level, and a same-candle sweep or
    displacement in the same direction.
    """
    if df is None or len(df) < max(lookback + 2, 10):
        return "none"

    resistance, support, tolerance, resistance_touches, support_touches = _key_levels(df, lookback)
    last = df.iloc[-1]
    high = float(last["high"])
    low = float(last["low"])
    open_ = float(last["open"])
    close = float(last["close"])
    candle_range = max(high - low, 1e-12)
    body = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low

    sweep = liquidity_sweep(df, min(10, len(df) - 1))
    impulse = displacement(df)

    bearish = (
        resistance_touches >= 2
        and high >= resistance - tolerance
        and close < resistance - tolerance * 0.15
        and upper_wick >= max(body * 1.15, candle_range * 0.28)
        and close <= low + candle_range * 0.45
        and (sweep == "sell_side_rejection" or impulse == "bearish")
    )
    bullish = (
        support_touches >= 2
        and low <= support + tolerance
        and close > support + tolerance * 0.15
        and lower_wick >= max(body * 1.15, candle_range * 0.28)
        and close >= low + candle_range * 0.55
        and (sweep == "buy_side_rejection" or impulse == "bullish")
    )

    if bearish and not bullish:
        return "strong_resistance_rejection"
    if bullish and not bearish:
        return "strong_support_rejection"
    return "none"


def breakout_retest_role_reversal(df: pd.DataFrame, lookback: int = 10) -> str:
    """Detect breakout -> retest -> role reversal using closed candles only."""
    if df is None or len(df) < lookback + 3:
        return "none"

    start = max(0, len(df) - lookback * 3)
    recent = df.iloc[start:].reset_index(drop=True)
    if len(recent) < lookback + 2:
        return "none"

    avg_range = float((recent["high"] - recent["low"]).tail(lookback).mean())
    tolerance = max(avg_range * 0.15, 1e-12)

    for breakout_idx in range(len(recent) - 2, lookback - 1, -1):
        prior = recent.iloc[breakout_idx - lookback:breakout_idx]
        breakout = recent.iloc[breakout_idx]
        resistance = float(prior["high"].max())
        support = float(prior["low"].min())

        if float(breakout["close"]) > resistance:
            for retest_idx in range(breakout_idx + 1, len(recent)):
                retest = recent.iloc[retest_idx]
                if float(retest["low"]) <= resistance + tolerance and float(retest["close"]) > resistance:
                    return "bullish_role_reversal"

        if float(breakout["close"]) < support:
            for retest_idx in range(breakout_idx + 1, len(recent)):
                retest = recent.iloc[retest_idx]
                if float(retest["high"]) >= support - tolerance and float(retest["close"]) < support:
                    return "bearish_role_reversal"

    return "none"
