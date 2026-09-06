import pandas as pd


def _valid(df: pd.DataFrame, minimum: int = 2) -> bool:
    return df is not None and not df.empty and len(df) >= minimum


def market_structure(df: pd.DataFrame, lookback: int = 3) -> str:
    """Latest closed-candle market-structure break."""
    if not _valid(df, lookback + 2):
        return "neutral"
    prior = df.iloc[-lookback - 1:-1]
    last = df.iloc[-1]
    if float(last["close"]) > float(prior["high"].max()):
        return "bullish_bos"
    if float(last["close"]) < float(prior["low"].min()):
        return "bearish_bos"
    return "neutral"


def liquidity_sweep(df: pd.DataFrame, lookback: int = 10) -> str:
    """Sweep prior liquidity and close back through the swept level."""
    if not _valid(df, lookback + 1):
        return "none"
    prior = df.iloc[-lookback - 1:-1]
    last = df.iloc[-1]
    high = float(prior["high"].max())
    low = float(prior["low"].min())
    if float(last["high"]) > high and float(last["close"]) < high:
        return "sell_side_rejection"
    if float(last["low"]) < low and float(last["close"]) > low:
        return "buy_side_rejection"
    return "none"


def displacement(df: pd.DataFrame) -> str:
    """Directional displacement with both body-quality and range expansion."""
    if not _valid(df, 3):
        return "none"
    previous = df.iloc[-2]
    last = df.iloc[-1]
    previous_range = max(float(previous["high"] - previous["low"]), 1e-12)
    last_range = max(float(last["high"] - last["low"]), 1e-12)
    body = abs(float(last["close"] - last["open"]))
    if body / last_range < 0.65 or body < previous_range * 0.60:
        return "none"
    if float(last["close"]) > float(last["open"]):
        return "bullish"
    if float(last["close"]) < float(last["open"]):
        return "bearish"
    return "none"


def _levels(df: pd.DataFrame, lookback: int = 20):
    if not _valid(df, lookback + 3):
        return None
    prior = df.iloc[-lookback - 1:-1].copy()
    highs = prior["high"].astype(float)
    lows = prior["low"].astype(float)
    swing_highs = []
    swing_lows = []
    for i in range(2, len(prior) - 2):
        window = prior.iloc[i - 2:i + 3]
        h = float(prior.iloc[i]["high"])
        l = float(prior.iloc[i]["low"])
        if h >= float(window["high"].max()):
            swing_highs.append(h)
        if l <= float(window["low"].min()):
            swing_lows.append(l)
    resistance = max(swing_highs) if swing_highs else float(highs.max())
    support = min(swing_lows) if swing_lows else float(lows.min())
    median_range = float((highs - lows).tail(10).median())
    tolerance = max(median_range * 0.08, abs(resistance - support) * 0.003, 1e-12)
    resistance_touches = int((highs.sub(resistance).abs() <= tolerance).sum())
    support_touches = int((lows.sub(support).abs() <= tolerance).sum())
    return resistance, support, tolerance, resistance_touches, support_touches


def strong_level_rejection(df: pd.DataFrame, lookback: int = 20) -> str:
    """Strict MMC support/resistance rejection on the latest closed candle."""
    levels = _levels(df, lookback)
    if levels is None:
        return "none"
    resistance, support, tolerance, resistance_touches, support_touches = levels
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

    sell = (
        resistance_touches >= 2
        and high >= resistance - tolerance
        and close < resistance
        and close <= low + candle_range * 0.48
        and upper_wick >= max(body * 1.25, candle_range * 0.30)
        and (sweep == "sell_side_rejection" or impulse == "bearish")
    )
    buy = (
        support_touches >= 2
        and low <= support + tolerance
        and close > support
        and close >= low + candle_range * 0.52
        and lower_wick >= max(body * 1.25, candle_range * 0.30)
        and (sweep == "buy_side_rejection" or impulse == "bullish")
    )
    if sell and not buy:
        return "strong_resistance_rejection"
    if buy and not sell:
        return "strong_support_rejection"
    return "none"


def breakout_retest_role_reversal(df: pd.DataFrame, lookback: int = 10) -> str:
    """Latest closed-candle breakout/retest role reversal only."""
    if not _valid(df, lookback + 4):
        return "none"
    recent = df.iloc[-lookback * 3:].reset_index(drop=True)
    last_idx = len(recent) - 1
    median_range = float((recent["high"] - recent["low"]).tail(lookback).median())
    tolerance = max(median_range * 0.10, 1e-12)

    for breakout_idx in range(max(lookback, last_idx - 4), last_idx):
        prior = recent.iloc[breakout_idx - lookback:breakout_idx]
        breakout = recent.iloc[breakout_idx]
        resistance = float(prior["high"].max())
        support = float(prior["low"].min())
        last = recent.iloc[last_idx]
        if float(breakout["close"]) > resistance:
            if float(last["low"]) <= resistance + tolerance and float(last["close"]) > resistance:
                return "bullish_role_reversal"
        if float(breakout["close"]) < support:
            if float(last["high"]) >= support - tolerance and float(last["close"]) < support:
                return "bearish_role_reversal"
    return "none"
