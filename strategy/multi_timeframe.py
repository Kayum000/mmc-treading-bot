import pandas as pd

from config import CONFIG
from strategy.mmc import market_structure, liquidity_sweep, displacement, breakout_retest_role_reversal, strong_level_rejection


def timeframe_components(df: pd.DataFrame, side: str) -> dict:
    """Return auditable, indicator-free MMC conditions for one timeframe."""
    if df is None or df.empty:
        return {
            "score": 0, "trend": False, "structure": "neutral", "sweep": "none",
            "displacement": "none", "rejection": "none", "trigger": False,
            "structure_ok": False, "sweep_ok": False, "displacement_ok": False,
            "rejection_ok": False, "role_reversal": "none", "role_reversal_ok": False,
        }

    structure = market_structure(df, CONFIG.swing_lookback)
    sweep = liquidity_sweep(df, CONFIG.sweep_lookback)
    impulse = displacement(df)
    rejection = strong_level_rejection(df)
    role_reversal = breakout_retest_role_reversal(df)

    if side == "buy":
        structure_ok = structure == "bullish_bos"
        sweep_ok = sweep == "buy_side_rejection"
        displacement_ok = impulse == "bullish"
        rejection_ok = rejection == "strong_support_rejection"
        role_reversal_ok = role_reversal == "bullish_role_reversal"
    else:
        structure_ok = structure == "bearish_bos"
        sweep_ok = sweep == "sell_side_rejection"
        displacement_ok = impulse == "bearish"
        rejection_ok = rejection == "strong_resistance_rejection"
        role_reversal_ok = role_reversal == "bearish_role_reversal"

    # Clean MMC: a timeframe has directional confirmation when structure has
    # broken in that direction, or a confirmed role reversal/rejection exists.
    trend_ok = structure_ok or role_reversal_ok or rejection_ok
    score = (
        2 * int(structure_ok)
        + 2 * int(sweep_ok)
        + int(displacement_ok)
        + 2 * int(rejection_ok)
        + 2 * int(role_reversal_ok)
    )

    return {
        "score": score,
        "trend": trend_ok,
        "structure": structure,
        "sweep": sweep,
        "displacement": impulse,
        "rejection": rejection,
        "trigger": sweep_ok and displacement_ok,
        "structure_ok": structure_ok,
        "sweep_ok": sweep_ok,
        "displacement_ok": displacement_ok,
        "rejection_ok": rejection_ok,
        "role_reversal": role_reversal,
        "role_reversal_ok": role_reversal_ok,
    }


def multi_timeframe_score(frames: dict[str, pd.DataFrame], side: str) -> int:
    """Weight clean MMC structure: 30m=3, 15m=2, 5m=1."""
    weights = {"30m": 3, "15m": 2, "5m": 1}
    return sum(timeframe_components(df, side)["score"] * weights.get(tf, 1) for tf, df in frames.items())


def confirmation_profile(frames: dict[str, pd.DataFrame], side: str) -> dict:
    """Build the final MMC confirmation chain: HTF -> setup -> entry."""
    parts = {tf: timeframe_components(frames[tf], side) for tf in ("30m", "15m", "5m")}
    return {
        "score": sum(parts[tf]["score"] * {"30m": 3, "15m": 2, "5m": 1}[tf] for tf in parts),
        "30m": parts["30m"],
        "15m": parts["15m"],
        "5m": parts["5m"],
        "higher_timeframe_trend": bool(parts["30m"]["trend"] and parts["15m"]["trend"]),
        "entry_trigger": bool(parts["5m"]["trigger"] or parts["5m"]["rejection_ok"]),
        "role_reversal_confirmation": bool(
            parts["30m"]["role_reversal_ok"] or parts["15m"]["role_reversal_ok"]
            or parts["30m"]["rejection_ok"] or parts["15m"]["rejection_ok"]
        ),
        "opposite_structure": bool(
            parts["30m"]["structure"] == ("bearish_bos" if side == "buy" else "bullish_bos")
            or parts["15m"]["structure"] == ("bearish_bos" if side == "buy" else "bullish_bos")
        ),
    }
