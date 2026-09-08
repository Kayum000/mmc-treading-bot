"""Advanced MMC quality gate.

Keeps the canonical Mirror MMC directional decision intact and adds a strict
confirmation-quality filter. No EMA/RSI/MACD/MTF is introduced.
"""
from __future__ import annotations

from strategy.mmc import Signal, generate_signal as _base_generate_signal, level_for_side


ADVANCED_BODY_RATIO = 0.60
ADVANCED_RANGE_LOOKBACK = 20
ADVANCED_RANGE_MULTIPLIER = 1.00


def _advanced_confirmation_quality(df, side: str) -> tuple[bool, str]:
    if df is None or df.empty or len(df) < ADVANCED_RANGE_LOOKBACK:
        return False, "Advanced MMC: confirmation quality যাচাইয়ের জন্য পর্যাপ্ত 1m candle নেই।"

    r = df.iloc[-1]
    high = float(r["high"])
    low = float(r["low"])
    open_ = float(r["open"])
    close = float(r["close"])
    candle_range = max(high - low, 1e-12)
    body_ratio = abs(close - open_) / candle_range

    ranges = (df["high"].astype(float) - df["low"].astype(float)).tail(ADVANCED_RANGE_LOOKBACK)
    median_range = max(float(ranges.median()), 1e-12)

    if body_ratio < ADVANCED_BODY_RATIO:
        return False, (
            f"Advanced MMC filter: confirmation candle body/range {body_ratio:.2f} < "
            f"{ADVANCED_BODY_RATIO:.2f}; weak confirmation।"
        )

    if candle_range < median_range * ADVANCED_RANGE_MULTIPLIER:
        return False, (
            f"Advanced MMC filter: confirmation range {candle_range:.8f} < "
            f"20-candle median {median_range:.8f}; insufficient displacement।"
        )

    return True, (
        f"Advanced MMC quality passed: body/range={body_ratio:.2f}, "
        f"range/20-candle-median={candle_range / median_range:.2f}।"
    )


def generate_signal(df):
    """Generate canonical MMC signal, then require advanced confirmation quality."""
    base = _base_generate_signal(df)
    if base.action not in {"BUY", "SELL"}:
        return base

    ok, quality_reason = _advanced_confirmation_quality(df, base.action)
    if not ok:
        return Signal("NO_TRADE", base.buy_score, base.sell_score, quality_reason)

    return Signal(
        base.action,
        base.buy_score,
        base.sell_score,
        f"{base.reason} Advanced quality gate passed: {quality_reason}",
    )


__all__ = ["Signal", "generate_signal", "level_for_side"]
