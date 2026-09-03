import pandas as pd

from config import CONFIG
from strategy.mmc import market_structure, liquidity_sweep, displacement, breakout_retest_role_reversal


def add_ema(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = out["close"].ewm(span=CONFIG.fast_ema, adjust=False).mean()
    out["ema_trend"] = out["close"].ewm(span=CONFIG.trend_ema, adjust=False).mean()
    return out


def timeframe_bias(df: pd.DataFrame) -> str:
    df = add_ema(df)
    if len(df) < CONFIG.trend_ema:
        return "neutral"
    close = df["close"].iloc[-1]
    fast = df["ema_fast"].iloc[-1]
    trend = df["ema_trend"].iloc[-1]
    structure = market_structure(df, CONFIG.swing_lookback)
    role_reversal = breakout_retest_role_reversal(df)
    if close > trend and fast > trend and (
        structure == "bullish_bos" or role_reversal == "bullish_role_reversal"
    ):
        return "bullish"
    if close < trend and fast < trend and (
        structure == "bearish_bos" or role_reversal == "bearish_role_reversal"
    ):
        return "bearish"
    return "neutral"


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


def timeframe_components(df: pd.DataFrame, side: str) -> dict[str, bool | str | int]:
    """Return auditable MMC conditions for one timeframe without changing scoring."""
    df = add_ema(df)
    if df.empty:
        return {"score": 0, "trend": False, "structure": "neutral", "sweep": "none", "displacement": "none", "trigger": False, "structure_ok": False, "sweep_ok": False, "displacement_ok": False, "role_reversal": "none", "role_reversal_ok": False}

    close = df["close"].iloc[-1]
    fast = df["ema_fast"].iloc[-1]
    trend = df["ema_trend"].iloc[-1]
    structure = market_structure(df, CONFIG.swing_lookback)
    sweep = liquidity_sweep(df, CONFIG.sweep_lookback)
    impulse = displacement(df)
    role_reversal = breakout_retest_role_reversal(df)

    if side == "buy":
        ema_trend_ok = close > trend and fast > trend
        structure_ok = structure == "bullish_bos"
        sweep_ok = sweep == "buy_side_rejection"
        displacement_ok = impulse == "bullish"
        role_reversal_ok = role_reversal == "bullish_role_reversal"
    else:
        ema_trend_ok = close < trend and fast < trend
        structure_ok = structure == "bearish_bos"
        sweep_ok = sweep == "sell_side_rejection"
        displacement_ok = impulse == "bearish"
        role_reversal_ok = role_reversal == "bearish_role_reversal"

    # A confirmed breakout/retest role reversal is itself valid structure
    # confirmation. Do not require the retest candle to also make a fresh BOS.
    trend_ok = ema_trend_ok and (structure_ok or role_reversal_ok)

    return {
        "score": score_timeframe(df, side),
        "trend": trend_ok,
        "structure": structure,
        "sweep": sweep,
        "displacement": impulse,
        "trigger": sweep_ok or displacement_ok,
        "structure_ok": structure_ok,
        "sweep_ok": sweep_ok,
        "displacement_ok": displacement_ok,
        "role_reversal": role_reversal,
        "role_reversal_ok": role_reversal_ok,
    }


def multi_timeframe_score(frames: dict[str, pd.DataFrame], side: str) -> int:
    """Weight higher timeframe more heavily: 30m=3, 15m=2, 5m=1."""
    weights = {"30m": 3, "15m": 2, "5m": 1}
    return sum(score_timeframe(df, side) * weights.get(tf, 1) for tf, df in frames.items())


def confirmation_profile(frames: dict[str, pd.DataFrame], side: str) -> dict:
    """Build a strict but explainable confirmation profile for final signal gating."""
    parts = {tf: timeframe_components(frames[tf], side) for tf in ("30m", "15m", "5m")}
    return {
        "score": sum(parts[tf]["score"] * {"30m": 3, "15m": 2, "5m": 1}[tf] for tf in parts),
        "30m": parts["30m"],
        "15m": parts["15m"],
        "5m": parts["5m"],
        "higher_timeframe_trend": bool(parts["30m"]["trend"] and parts["15m"]["trend"]),
        "entry_trigger": bool(parts["5m"]["trigger"]),
        "role_reversal_confirmation": bool(parts["30m"]["role_reversal_ok"] or parts["15m"]["role_reversal_ok"]),
        "opposite_structure": bool(
            parts["30m"]["structure"] == ("bearish_bos" if side == "buy" else "bullish_bos")
            or parts["15m"]["structure"] == ("bearish_bos" if side == "buy" else "bullish_bos")
        ),
    }
