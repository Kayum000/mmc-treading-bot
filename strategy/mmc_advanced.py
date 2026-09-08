"""Balanced Advanced MMC quality gate.

Keeps the canonical Mirror MMC directional decision intact while filtering
weak/choppy confirmation candles. No EMA/RSI/MACD/MTF is introduced.
"""
from __future__ import annotations

from strategy.mmc import Signal, generate_signal as _base_generate_signal, level_for_side


ADVANCED_BODY_RATIO = 0.55
ADVANCED_RANGE_LOOKBACK = 20
ADVANCED_RANGE_MULTIPLIER = 0.90
ADVANCED_CLOSE_LOCATION = 0.25


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
    range_ratio = candle_range / median_range

    if body_ratio < ADVANCED_BODY_RATIO:
        return False, (
            f"Advanced MMC filter: body/range {body_ratio:.2f} < "
            f"{ADVANCED_BODY_RATIO:.2f}; weak confirmation।"
        )

    if range_ratio < ADVANCED_RANGE_MULTIPLIER:
        return False, (
            f"Advanced MMC filter: range/20-candle-median {range_ratio:.2f} < "
            f"{ADVANCED_RANGE_MULTIPLIER:.2f}; weak displacement।"
        )

    # Direction-aware close location: BUY should finish near the high,
    # SELL near the low. This removes many indecisive rejection candles
    # without requiring an external indicator.
    if side == "BUY":
        close_from_high = (high - close) / candle_range
        if close_from_high > ADVANCED_CLOSE_LOCATION:
            return False, (
                f"Advanced MMC filter: BUY close is too far from high "
                f"({close_from_high:.2f} > {ADVANCED_CLOSE_LOCATION:.2f})।"
            )
    elif side == "SELL":
        close_from_low = (close - low) / candle_range
        if close_from_low > ADVANCED_CLOSE_LOCATION:
            return False, (
                f"Advanced MMC filter: SELL close is too far from low "
                f"({close_from_low:.2f} > {ADVANCED_CLOSE_LOCATION:.2f})।"
            )

    return True, (
        f"Advanced quality passed: body/range={body_ratio:.2f}, "
        f"range/median={range_ratio:.2f}, side={side}, "
        f"close-location<= {ADVANCED_CLOSE_LOCATION:.2f}।"
    )


def generate_signal(df):
    """Generate canonical MMC signal, then require balanced advanced quality."""
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
        f"{base.reason} Advanced balanced gate passed: {quality_reason}",
    )


__all__ = ["Signal", "generate_signal", "level_for_side"]
