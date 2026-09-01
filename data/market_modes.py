"""Market-mode data adapters.

Modes are signal/data modes only; this module never submits trades.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MarketMode = Literal["REAL_MARKET", "CRYPTO"]


@dataclass(frozen=True)
class MarketSpec:
    mode: MarketMode
    symbol: str
    source: str


REAL_MARKET = "REAL_MARKET"
CRYPTO = "CRYPTO"


def make_market(mode: MarketMode, symbol: str) -> MarketSpec:
    if mode not in (REAL_MARKET, CRYPTO):
        raise ValueError(f"Unsupported market mode: {mode}")
    if not symbol.strip():
        raise ValueError("symbol must not be empty")
    source = "user-authorized-live-feed" if mode == REAL_MARKET else "binance-public-market-data"
    return MarketSpec(mode=mode, symbol=symbol.upper(), source=source)
