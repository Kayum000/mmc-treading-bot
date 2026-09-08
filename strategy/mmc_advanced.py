"""Adaptive Advanced MMC engine.

Replaces the previous balanced candle gate with a structure-first confluence
layer. The canonical Mirror MMC remains the directional anchor, but a trade
is accepted only when the recent liquidity/structure story agrees with it.
No EMA/RSI/MACD/MTF is used.
"""
from __future__ import annotations

from strategy.mmc import (
    Signal,
    generate_signal as _base_generate_signal,
    get_mirror_projection,
    level_for_side,
    liquidity_sweep,
    market_structure,
)

SWEEP_WINDOW = 6
STRUCTURE_LOOKBACK = 4
RANGE_LOOKBACK = 20
DISPLACEMENT_BODY = 0.60
DISPLACEMENT_RANGE_RATIO = 1.15
FVG_LOOKBACK = 6
CHOP_LOOKBACK = 8
MIN_CONFLUENCE = 4


def _valid(df, n=1):
    return df is not None and not df.empty and len(df) >= n


def _rng(r):
    return max(float(r["high"]) - float(r["low"]), 1e-12)


def _body_ratio(r):
    return abs(float(r["close"]) - float(r["open"])) / _rng(r)


def _bull(r):
    return float(r["close"]) > float(r["open"])


def _bear(r):
    return float(r["close"]) < float(r["open"])


def _recent_sweep(df, side: str):
    if not _valid(df, SWEEP_WINDOW + 2):
        return False, None
    wanted = "buy_side_rejection" if side == "BUY" else "sell_side_rejection"
    start = max(0, len(df) - SWEEP_WINDOW)
    for i in range(start, len(df)):
        part = df.iloc[: i + 1]
        if liquidity_sweep(part, min(10, len(part) - 1)) == wanted:
            return True, i
    return False, None


def _post_sweep_structure(df, side: str, sweep_idx):
    if sweep_idx is None or sweep_idx >= len(df) - 1:
        return False
    for i in range(sweep_idx + 1, len(df)):
        part = df.iloc[: i + 1]
        struct = market_structure(part, STRUCTURE_LOOKBACK)
        if side == "BUY" and struct == "bullish_bos":
            return True
        if side == "SELL" and struct == "bearish_bos":
            return True
    return False


def _displacement_quality(df, side: str):
    if not _valid(df, RANGE_LOOKBACK + 1):
        return False
    r = df.iloc[-1]
    if side == "BUY" and not _bull(r):
        return False
    if side == "SELL" and not _bear(r):
        return False
    body = _body_ratio(r)
    ranges = (df["high"].astype(float) - df["low"].astype(float)).iloc[:-1].tail(RANGE_LOOKBACK)
    median_range = max(float(ranges.median()), 1e-12)
    return body >= DISPLACEMENT_BODY and _rng(r) / median_range >= DISPLACEMENT_RANGE_RATIO


def _fvg_present(df, side: str):
    if not _valid(df, 3):
        return False
    x = df.tail(FVG_LOOKBACK).reset_index(drop=True)
    for i in range(2, len(x)):
        a = x.iloc[i - 2]
        c = x.iloc[i]
        if side == "BUY" and float(c["low"]) > float(a["high"]):
            return True
        if side == "SELL" and float(c["high"]) < float(a["low"]):
            return True
    return False


def _zone_reclaim(df, side: str):
    mirror = get_mirror_projection(df, side, 20)
    if not mirror:
        return False
    r = df.iloc[-1]
    zone = float(mirror["zone"])
    tol = float(mirror["tolerance"])
    close = float(r["close"])
    low = float(r["low"])
    high = float(r["high"])
    if side == "BUY":
        return low <= zone + tol and close > zone
    return high >= zone - tol and close < zone


def _anti_chop(df, side: str):
    if not _valid(df, CHOP_LOOKBACK + 2):
        return False
    x = df.tail(CHOP_LOOKBACK)
    ranges = x["high"].astype(float) - x["low"].astype(float)
    median = max(float(ranges.median()), 1e-12)
    current = float(ranges.iloc[-1])
    if current < median * 1.05:
        return False
    hi = float(x.iloc[:-1]["high"].max())
    lo = float(x.iloc[:-1]["low"].min())
    mid = lo + (hi - lo) * 0.5
    close = float(x.iloc[-1]["close"])
    if side == "BUY" and close <= mid:
        return False
    if side == "SELL" and close >= mid:
        return False
    return True


def _confluence(df, side: str):
    sweep, sweep_idx = _recent_sweep(df, side)
    checks = {
        "liquidity_sweep": sweep,
        "post_sweep_structure": _post_sweep_structure(df, side, sweep_idx) if sweep else False,
        "displacement": _displacement_quality(df, side),
        "fvg": _fvg_present(df, side),
        "mirror_zone_reclaim": _zone_reclaim(df, side),
        "anti_chop": _anti_chop(df, side),
    }
    return sum(bool(v) for v in checks.values()), checks


def _reason(score, checks):
    passed = [name for name, ok in checks.items() if ok]
    return f"Advanced MMC confluence {score}/{len(checks)} passed: " + ", ".join(passed)


def generate_signal(df):
    """Generate MMC direction, then apply adaptive structure confluence."""
    base = _base_generate_signal(df)
    if base.action not in {"BUY", "SELL"}:
        return base
    score, checks = _confluence(df, base.action)
    if score < MIN_CONFLUENCE:
        return Signal(
            "NO_TRADE",
            base.buy_score,
            base.sell_score,
            f"Advanced MMC rejected {base.action}: {_reason(score, checks)}; minimum={MIN_CONFLUENCE}.",
        )
    return Signal(
        base.action,
        base.buy_score,
        base.sell_score,
        f"{base.reason} | {_reason(score, checks)}.",
    )


__all__ = ["Signal", "generate_signal", "level_for_side"]
