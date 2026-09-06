import pandas as pd

from config import CONFIG
from strategy.mmc_clean import (
    market_structure,
    liquidity_sweep,
    displacement,
    breakout_retest_role_reversal,
    strong_level_rejection,
)


def timeframe_components(df: pd.DataFrame, side: str) -> dict:
    """Return indicator-free MMC components for one timeframe."""
    empty = {
        "score": 0, "trend": False, "structure": "neutral", "sweep": "none",
        "displacement": "none", "rejection": "none", "trigger": False,
        "structure_ok": False, "sweep_ok": False, "displacement_ok": False,
        "rejection_ok": False, "role_reversal": "none", "role_reversal_ok": False,
    }
    if df is None or df.empty:
        return empty

    structure = market_structure(df, CONFIG.swing_lookback)
    sweep = liquidity_sweep(df, CONFIG.sweep_lookback)
    impulse = displacement(df)
    rejection = strong_level_rejection(df)
    role_reversal = breakout_retest_role_reversal(df)

    buy = side == "buy"
    structure_ok = structure == ("bullish_bos" if buy else "bearish_bos")
    sweep_ok = sweep == ("buy_side_rejection" if buy else "sell_side_rejection")
    displacement_ok = impulse == ("bullish" if buy else "bearish")
    rejection_ok = rejection == ("strong_support_rejection" if buy else "strong_resistance_rejection")
    role_reversal_ok = role_reversal == ("bullish_role_reversal" if buy else "bearish_role_reversal")

    # HTF direction comes only from structure or confirmed role reversal.
    # A rejection alone is an entry setup, not a higher-timeframe trend.
    trend_ok = structure_ok or role_reversal_ok
    # A 5m trigger must contain a rejection/sweep structure, not merely a large candle.
    trigger_ok = rejection_ok and (sweep_ok or displacement_ok)
    score = (
        3 * int(structure_ok)
        + 2 * int(role_reversal_ok)
        + 2 * int(sweep_ok)
        + 2 * int(rejection_ok)
        + int(displacement_ok)
    )

    return {
        "score": score,
        "trend": trend_ok,
        "structure": structure,
        "sweep": sweep,
        "displacement": impulse,
        "rejection": rejection,
        "trigger": trigger_ok,
        "structure_ok": structure_ok,
        "sweep_ok": sweep_ok,
        "displacement_ok": displacement_ok,
        "rejection_ok": rejection_ok,
        "role_reversal": role_reversal,
        "role_reversal_ok": role_reversal_ok,
    }


def multi_timeframe_score(frames: dict[str, pd.DataFrame], side: str) -> int:
    """Weight MMC evidence by timeframe: 30m=3, 15m=2, 5m=1."""
    weights = {"30m": 3, "15m": 2, "5m": 1}
    return sum(timeframe_components(frames[tf], side)["score"] * weights[tf] for tf in weights if tf in frames)


def confirmation_profile(frames: dict[str, pd.DataFrame], side: str) -> dict:
    """Build the MMC chain: 30m direction -> 15m direction -> 5m trigger."""
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
