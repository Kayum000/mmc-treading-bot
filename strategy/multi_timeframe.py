import pandas as pd

from config import CONFIG
from strategy.mmc import market_structure, liquidity_sweep, displacement


def add_ema(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = out["close"].ewm(span=CONFIG.fast_ema, adjust=False).mean()
    out["ema_trend"] = out["close"].ewm(span=CONFIG.trend_ema, adjust=False).mean()
    return out


def score_timeframe(df: pd.DataFrame, side: str) -> int:
    df = add_ema(df)
    score = 0
    close = df["close"].iloc[-1]
    fast = df["ema_fast"].iloc[-1]
    trend = df["ema_trend"].iloc[-1]
    structure = market_structure(df, CONFIG.swing_lookback)
    sweep = liquidity_sweep(df, CONFIG.sweep_lookback)
    impulse = displacement(df)
    if side == "buy":
        score += int(close > trend)
        score += int(fast > trend)
        score += 2 * int(structure == "bullish_bos")
        score += 2 * int(sweep == "buy_side_rejection")
        score += int(impulse == "bullish")
    else:
        score += int(close < trend)
        score += int(fast < trend)
        score += 2 * int(structure == "bearish_bos")
        score += 2 * int(sweep == "sell_side_rejection")
        score += int(impulse == "bearish")
    return score


def multi_timeframe_score(frames: dict[str, pd.DataFrame], side: str) -> int:
    weights = {"15m": 3, "5m": 2, "1m": 1}
    return sum(score_timeframe(df, side) * weights.get(tf, 1) for tf, df in frames.items())
