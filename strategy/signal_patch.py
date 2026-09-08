"""Conservative signal-density layer for the live MMC engine.

The canonical Mirror MMC remains first priority. Valid canonical setups are
classified as A+ or A without changing the underlying entry decision. The
secondary fallback remains explicitly lower-tier and is never counted as A/A+.
"""
from __future__ import annotations

from strategy import mmc as _mmc

_ORIGINAL_GENERATE_SIGNAL = _mmc.generate_signal


def _grade_canonical(signal, df):
    """Attach an empirical setup grade to an already-valid canonical signal.

    A+ requires both a meaningful score margin and a strong confirmation body.
    A is a valid MMC confirmation with a smaller margin. No threshold here
    creates a signal; it only classifies a signal that the canonical gate has
    already accepted.
    """
    if signal.action not in {"BUY", "SELL"}:
        return signal

    margin = abs(int(signal.buy_score) - int(signal.sell_score))
    try:
        ratio = float(_mmc._ratio(df.iloc[-1]))
    except Exception:
        return signal

    if margin >= 4 and ratio >= 0.60:
        grade = "A+"
    elif margin >= 2 and ratio >= 0.45:
        grade = "A"
    else:
        # Canonical gate passed, but the classification is intentionally not
        # promoted to A/A+ until the stronger margin/body conditions are met.
        grade = "VALID"

    reason = f"{signal.reason} Setup grade: {grade} (score margin {margin}, confirmation body ratio {ratio:.2f})."
    return _mmc.Signal(signal.action, signal.buy_score, signal.sell_score, reason)


def _quality_fallback(df):
    minimum = max(_mmc.CONFIG.sweep_lookback + 1, _mmc.CONFIG.level_lookback + 5, 27)
    if not _mmc._valid(df, minimum):
        return None

    buy_score, sell_score, votes = _mmc.concept_scores(df)
    candidates = []
    if buy_score >= 7 and buy_score - sell_score >= 2:
        candidates.append("BUY")
    if sell_score >= 7 and sell_score - buy_score >= 2:
        candidates.append("SELL")
    if len(candidates) != 1:
        return None

    side = candidates[0]
    want = "bullish" if side == "BUY" else "bearish"
    r = df.iloc[-1]
    candle_ok = _mmc._dir(r) == want
    if not candle_ok:
        return None

    sweep = _mmc.liquidity_sweep(df, _mmc.CONFIG.sweep_lookback)
    structure = _mmc.market_structure(df, _mmc.CONFIG.swing_lookback)
    impulse = _mmc.displacement(df)
    side_votes = votes[side]
    confirmation = (
        side_votes.get("liquidity_sweep", False)
        or side_votes.get("mss_choch", False)
        or side_votes.get("bos", False)
        or side_votes.get("rejection_block", False)
        or side_votes.get("order_block_activation", False)
        or side_votes.get("mitigation", False)
        or side_votes.get("breaker_block", False)
        or sweep == ("buy_side_rejection" if side == "BUY" else "sell_side_rejection")
        or structure == ("bullish_bos" if side == "BUY" else "bearish_bos")
        or impulse == want
    )
    if not confirmation:
        return None

    return _mmc.Signal(
        side,
        buy_score,
        sell_score,
        f"Quality MMC fallback: {side} selected with supporting votes {buy_score}/22 vs {sell_score}/22, directional candle and independent price-action confirmation. Canonical Mirror gate did not complete, so this is a lower-tier setup (not A/A+); protection rules still apply."
    )


def generate_signal(df):
    """Use canonical Mirror MMC first, classify it, then use a lower-tier fallback."""
    primary = _ORIGINAL_GENERATE_SIGNAL(df)
    if primary.action in {"BUY", "SELL"}:
        return _grade_canonical(primary, df)
    fallback = _quality_fallback(df)
    return fallback if fallback is not None else primary
