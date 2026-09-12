"""Conservative 1-minute Quotex OTC candle strategy for signal generation only."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class OTCSignal:
    action: str
    confidence: float
    reason: str


def generate_signal(candles: pd.DataFrame) -> OTCSignal:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(candles.columns)
    if missing:
        raise ValueError(f"missing candle columns: {sorted(missing)}")

    x = candles.copy().sort_values("timestamp").drop_duplicates("timestamp")
    for c in ("open", "high", "low", "close"):
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=["open", "high", "low", "close"]).tail(60)
    if len(x) < 8:
        return OTCSignal("HOLD", 0.0, "insufficient closed OTC candle history")

    body = x["close"] - x["open"]
    rng = (x["high"] - x["low"]).replace(0, np.nan)
    body_ratio = (body.abs() / rng).fillna(0.0)
    direction = np.sign(body).astype(int)
    recent = direction.tail(4).to_numpy()
    last_body = float(body.iloc[-1])
    last_ratio = float(body_ratio.iloc[-1])

    if last_ratio < 0.45:
        return OTCSignal("HOLD", 0.0, "latest OTC candle body is too weak")

    up = int(np.sum(recent > 0))
    down = int(np.sum(recent < 0))
    if up >= 3 and last_body > 0:
        confidence = 0.70 + min(0.10, (last_ratio - 0.45) * 0.15)
        return OTCSignal("BUY", round(confidence, 2), f"{up}/4 recent candles bullish; body strength {last_ratio:.2f}")
    if down >= 3 and last_body < 0:
        confidence = 0.70 + min(0.10, (last_ratio - 0.45) * 0.15)
        return OTCSignal("SELL", round(confidence, 2), f"{down}/4 recent candles bearish; body strength {last_ratio:.2f}")

    return OTCSignal("HOLD", 0.0, "recent OTC candle direction is mixed")
