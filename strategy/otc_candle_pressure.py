"""OTC adapter that uses the same regime-adaptive candle strategy as Real Market.

The market data source remains Quotex OTC candles, but signal selection is
intentionally shared with the Real-Market adaptive engine so both modes use the
same TREND, BREAKOUT, RANGE, and HIGH_VOLATILITY rules.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from strategy.adaptive_real import generate_adaptive_signal


@dataclass
class OTCSignal:
    action: str
    confidence: float
    reason: str
    regime: str
    strategy: str


def generate_signal(candles: pd.DataFrame, ticks: pd.DataFrame | None = None) -> OTCSignal:
    """Use the shared adaptive candle logic without tick-pressure fallback."""
    result = generate_adaptive_signal(candles)

    return OTCSignal(
        action=result.action,
        confidence=result.confidence,
        reason=result.reason,
        regime=result.regime,
        strategy=result.strategy,
    )
