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
