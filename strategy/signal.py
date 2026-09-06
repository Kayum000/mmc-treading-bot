"""Compatibility exports for the canonical MMC engine.

All strategy decision logic lives in strategy/mmc.py. This module contains no
second strategy implementation and no multi-timeframe logic.
"""
from strategy.mmc import Signal, generate_signal, level_for_side


def generate_1m_signal(df):
    """Backward-compatible name for the canonical 1-minute MMC decision."""
    return generate_signal(df)


__all__ = ["Signal", "generate_signal", "generate_1m_signal", "level_for_side"]
