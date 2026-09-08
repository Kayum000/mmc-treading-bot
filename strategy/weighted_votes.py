"""Weighted/clustered 22-vote confirmation engine.

This module is intentionally separate from the live MM-free strategy.
It reuses the existing 22 concept detectors, but prevents redundant
liquidity events from receiving multiple independent votes.

Directional output is BUY / SELL / NO_TRADE. Premium/Discount, OTE and
Kill Zone are treated as filters rather than directional score boosters.
"""
from __future__ import annotations

from strategy.mmc import Signal, concept_scores

# Stronger candidates from the July/August screening audit.
WEIGHTS = {
    "liquidity_sweep": 3,
    "inducement": 2,
    "liquidity_generation": 1,
    "mss_choch": 2,
    "bos": 1,
    "displacement": 1,
    "ifvg": 3,
    "fvg": 2,
    "rejection_block": 1,
    "order_block_activation": 1,
    "mitigation": 1,
    "accumulation": 1,
    "propulsion_block": 1,
}

# These are contextual gates, not independent directional votes.
FILTERS = ("premium_discount", "ote", "kill_zone")

# These duplicate or underperformed enough in the screening audit to be
# disabled by default. The underlying detectors remain intact in mmc.py.
DISABLED = (
    "engineering_liquidity",
    "judas_stop_hunt",
    "liquidity_void",
    "ifc",
    "breaker_block",
    "distribution_completion",
)


def _weighted_side(votes: dict[str, bool]) -> int:
    """Return a clustered score; duplicate liquidity votes are not counted."""
    score = 0
    for name, weight in WEIGHTS.items():
        if votes.get(name, False):
            score += weight
    return score


def weighted_scores(df):
    """Return BUY score, SELL score and raw 22-vote maps."""
    _, _, raw = concept_scores(df)
    return _weighted_side(raw["BUY"]), _weighted_side(raw["SELL"]), raw


def generate_signal(
    df,
    min_score: int = 5,
    require_filter: bool = True,
) -> Signal:
    """Generate a weighted vote signal without modifying the live MM-free path.

    A side needs at least ``min_score`` weighted points. When ``require_filter``
    is true, at least two of Premium/Discount, OTE and Kill Zone must be true.
    Ties and weak scores return NO_TRADE.
    """
    if df is None or len(df) < 12:
        return Signal("NO_TRADE", 0, 0, "Weighted votes: insufficient history.")

    buy, sell, raw = weighted_scores(df)

    def filter_count(side: str) -> int:
        return sum(bool(raw[side].get(name, False)) for name in FILTERS)

    bf = filter_count("BUY")
    sf = filter_count("SELL")

    buy_ok = buy >= min_score and (not require_filter or bf >= 2)
    sell_ok = sell >= min_score and (not require_filter or sf >= 2)

    if buy_ok and not sell_ok and buy > sell:
        return Signal("BUY", buy, sell, f"Weighted 22-vote BUY | score={buy} | filters={bf}/3.")
    if sell_ok and not buy_ok and sell > buy:
        return Signal("SELL", buy, sell, f"Weighted 22-vote SELL | score={sell} | filters={sf}/3.")

    return Signal("NO_TRADE", buy, sell,
                  f"Weighted 22-vote | BUY={buy} ({bf}/3 filters) | SELL={sell} ({sf}/3 filters).")


__all__ = [
    "DISABLED",
    "FILTERS",
    "WEIGHTS",
    "generate_signal",
    "weighted_scores",
]
