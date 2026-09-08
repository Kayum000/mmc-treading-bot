"""Tick-Run Pressure Continuation strategy.

A new tick-level strategy derived from the uploaded EURUSD tick sample.
It does NOT use MMC, sweep, MSS, MTF, S/R, ORB, candle patterns, EMA/RSI/MACD,
or the previous TickFlow minute-imbalance logic.

Idea:
1. A persistent run of quote-mid moves indicates short-term directional pressure.
2. Require strong same-side bid/ask volume imbalance to confirm that the run is
   supported by liquidity pressure rather than a weak price drift.
3. Predict the direction of the next quote-mid tick.

This is intentionally tick-level; it should not be wired into the M1 live path
until a real tick feed is available and multi-day walk-forward validation passes.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class TickRunSignal:
    action: str
    confidence: float
    reason: str


def _prepare(ticks: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "askPrice", "bidPrice", "askVolume", "bidVolume"}
    missing = required - set(ticks.columns)
    if missing:
        raise ValueError(f"missing tick columns: {sorted(missing)}")
    x = ticks.copy()
    for c in ["askPrice", "bidPrice", "askVolume", "bidVolume"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    x["mid"] = (x["askPrice"] + x["bidPrice"]) / 2.0
    total = x["bidVolume"] + x["askVolume"]
    x["imbalance"] = (x["bidVolume"] - x["askVolume"]) / total.replace(0, np.nan)
    x["direction"] = np.sign(x["mid"].diff()).fillna(0)
    return x.dropna(subset=["imbalance"])


def generate_signal(ticks: pd.DataFrame, run_length: int = 8, imbalance_threshold: float = 0.60) -> TickRunSignal:
    x = _prepare(ticks)
    if len(x) < run_length + 2:
        return TickRunSignal("HOLD", 0.0, "insufficient tick history")

    d = x["direction"].to_numpy()
    imb = x["imbalance"].to_numpy()
    last = len(x) - 1
    run = d[last - run_length + 1:last + 1]
    if np.all(run > 0) and imb[last] >= imbalance_threshold:
        conf = min(0.99, 0.70 + 0.20 * (imb[last] - imbalance_threshold) / (1.0 - imbalance_threshold))
        return TickRunSignal("BUY", conf, f"{run_length}-tick upward run + strong bid-volume pressure")
    if np.all(run < 0) and imb[last] <= -imbalance_threshold:
        conf = min(0.99, 0.70 + 0.20 * ((-imb[last]) - imbalance_threshold) / (1.0 - imbalance_threshold))
        return TickRunSignal("SELL", conf, f"{run_length}-tick downward run + strong ask-volume pressure")
    return TickRunSignal("HOLD", 0.0, "run/pressure confirmation absent")


def backtest_labels(ticks: pd.DataFrame, run_length: int = 8, imbalance_threshold: float = 0.60) -> pd.DataFrame:
    x = _prepare(ticks)
    x["signal"] = "HOLD"
    d = x["direction"].to_numpy()
    imb = x["imbalance"].to_numpy()
    for i in range(run_length, len(x) - 1):
        run = d[i-run_length+1:i+1]
        if np.all(run > 0) and imb[i] >= imbalance_threshold:
            x.iat[i, x.columns.get_loc("signal")] = "BUY"
        elif np.all(run < 0) and imb[i] <= -imbalance_threshold:
            x.iat[i, x.columns.get_loc("signal")] = "SELL"
    x["future_direction"] = np.sign(x["mid"].shift(-1) - x["mid"])
    x["correct"] = ((x.signal == "BUY") & (x.future_direction > 0)) | ((x.signal == "SELL") & (x.future_direction < 0))
    return x
