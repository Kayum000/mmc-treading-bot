import pandas as pd


def _valid(df: pd.DataFrame, minimum: int = 2) -> bool:
    return df is not None and not df.empty and len(df) >= minimum


def market_structure(df: pd.DataFrame, lookback: int = 3) -> str:
    """Return a BOS direction from the latest closed candle only."""
    if not _valid(df, lookback + 2):
        return "neutral"
    prior = df.iloc[-lookback - 1:-1]
    last = df.iloc[-1]
    close = float(last["close"])
    if close > float(prior["high"].max()):
        return "bullish_bos"
    if close < float(prior["low"].min()):
        return "bearish_bos"
    return "neutral"


def liquidity_sweep(df: pd.DataFrame, lookback: int = 10) -> str:
    """Detect a liquidity grab that closes back inside the prior range."""
    if not _valid(df, lookback + 1):
        return "none"
    prior = df.iloc[-lookback - 1:-1]
    last = df.iloc[-1]
    prior_high = float(prior["high"].max())
    prior_low = float(prior["low"].min())
    if float(last["high"]) > prior_high and float(last["close"]) < prior_high:
        return "sell_side_rejection"
    if float(last["low"]) < prior_low and float(last["close"]) > prior_low:
        return "buy_side_rejection"
    return "none"


def displacement(df: pd.DataFrame) -> str:
    """Require a decisive candle body and range expansion."""
    if not _valid(df, 3):
        return "none"
    previous = df.iloc[-2]
    last = df.iloc[-1]
    previous_range = max(float(previous["high"] - previous["low"]), 1e-12)
    last_range = max(float(last["high"] - last["low"]), 1e-12)
    body = abs(float(last["close"] - last["open"]))
    if body / last_range < 0.65 or last_range < previous_range * 1.10:
        return "none"
    if float(last["close"]) > float(last["open"]):
        return "bullish"
    if float(last["close"]) < float(last["open"]):
        return "bearish"
    return "none"


def _swing_levels(prior: pd.DataFrame):
    """Return confirmed 5-candle swing highs/lows from closed candles."""
    highs = []
    lows = []
    for i in range(2, len(prior) - 2):
        window = prior.iloc[i - 2:i + 3]
        high = float(prior.iloc[i]["high"])
        low = float(prior.iloc[i]["low"])
        if high >= float(window["high"].max()):
            highs.append(high)
        if low <= float(window["low"].min()):
            lows.append(low)
    return highs, lows


def _cluster_levels(values, tolerance: float):
    """Cluster nearby swing prices so repeated tests form one MMC level."""
    if not values:
        return []
    levels = []
    for value in sorted(float(v) for v in values):
        if not levels or abs(value - levels[-1]["price"]) > tolerance:
            levels.append({"price": value, "touches": 1})
        else:
            current = levels[-1]
            current["price"] = (current["price"] * current["touches"] + value) / (current["touches"] + 1)
            current["touches"] += 1
    return levels


def get_mmc_levels(df: pd.DataFrame, lookback: int = 20):
    """Return confirmed support/resistance clusters without whole-range fallback."""
    if not _valid(df, lookback + 5):
        return None
    prior = df.iloc[-lookback - 1:-1].copy()
    ranges = (prior["high"].astype(float) - prior["low"].astype(float)).clip(lower=0)
    median_range = float(ranges.tail(10).median())
    if median_range <= 0:
        return None

    tolerance = max(median_range * 0.08, 1e-12)
    swing_highs, swing_lows = _swing_levels(prior)
    resistance_clusters = _cluster_levels(swing_highs, tolerance)
    support_clusters = _cluster_levels(swing_lows, tolerance)
    if not resistance_clusters and not support_clusters:
        return None

    latest_close = float(df.iloc[-1]["close"])
    resistance_candidates = [x for x in resistance_clusters if x["price"] >= latest_close - tolerance]
    support_candidates = [x for x in support_clusters if x["price"] <= latest_close + tolerance]

    strong_res = [x for x in resistance_candidates if x["touches"] >= 2]
    strong_sup = [x for x in support_candidates if x["touches"] >= 2]
    resistance = min(strong_res or resistance_candidates, key=lambda x: abs(x["price"] - latest_close)) if resistance_candidates else None
    support = min(strong_sup or support_candidates, key=lambda x: abs(x["price"] - latest_close)) if support_candidates else None
    return {
        "resistance": float(resistance["price"]) if resistance else None,
        "support": float(support["price"]) if support else None,
        "tolerance": tolerance,
        "resistance_touches": int(resistance["touches"]) if resistance else 0,
        "support_touches": int(support["touches"]) if support else 0,
    }


def strong_level_rejection(df: pd.DataFrame, lookback: int = 20) -> str:
    """Confirm a real support/resistance rejection on the latest closed candle."""
    levels = get_mmc_levels(df, lookback)
    if levels is None:
        return "none"

    resistance = levels["resistance"]
    support = levels["support"]
    tolerance = levels["tolerance"]
    resistance_touches = levels["resistance_touches"]
    support_touches = levels["support_touches"]
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
        resistance is not None
        and resistance_touches >= 2
        and high >= resistance - tolerance
        and close < resistance
        and close <= low + candle_range * 0.48
        and upper_wick >= max(body * 1.25, candle_range * 0.30)
        and (sweep == "sell_side_rejection" or impulse == "bearish")
    )
    buy = (
        support is not None
        and support_touches >= 2
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
    """Confirm a recent breakout followed by a same-level retest and close."""
    if not _valid(df, lookback + 5):
        return "none"
    recent = df.iloc[-lookback * 3:].reset_index(drop=True)
    last_idx = len(recent) - 1
    ranges = (recent["high"].astype(float) - recent["low"].astype(float)).clip(lower=0)
    tolerance = max(float(ranges.tail(lookback).median()) * 0.10, 1e-12)

    for breakout_idx in range(max(lookback, last_idx - 3), last_idx):
        prior = recent.iloc[breakout_idx - lookback:breakout_idx]
        breakout = recent.iloc[breakout_idx]
        last = recent.iloc[last_idx]
        resistance = float(prior["high"].max())
        support = float(prior["low"].min())
        if float(breakout["close"]) > resistance:
            if float(last["low"]) <= resistance + tolerance and float(last["close"]) > resistance:
                return "bullish_role_reversal"
        if float(breakout["close"]) < support:
            if float(last["high"]) >= support - tolerance and float(last["close"]) < support:
                return "bearish_role_reversal"
    return "none"
