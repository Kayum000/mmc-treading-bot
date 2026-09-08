"""TickFlow: EURUSD tick-level microstructure strategy.

Independent of the previous MTF/MMC/Sweep/MSS/SR/ORB approaches.
Uses only tick quote/volume information: midpoint, spread, bid/ask volume
imbalance, signed tick movement and tick arrival intensity.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TickSignal:
    action: str
    confidence: float
    reason: str


def _clean(ticks: pd.DataFrame) -> pd.DataFrame:
    if ticks is None or ticks.empty:
        return pd.DataFrame()
    x = ticks.copy()
    required = ["timestamp", "askPrice", "bidPrice", "askVolume", "bidVolume"]
    if any(c not in x.columns for c in required):
        return pd.DataFrame()
    x["timestamp"] = pd.to_datetime(x["timestamp"], unit="ms", utc=True, errors="coerce")
    for c in ("askPrice", "bidPrice", "askVolume", "bidVolume"):
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=required).sort_values("timestamp")
    x = x[(x["askPrice"] > 0) & (x["bidPrice"] > 0)]
    x["mid"] = (x["askPrice"] + x["bidPrice"]) / 2.0
    x["spread"] = x["askPrice"] - x["bidPrice"]
    denom = (x["bidVolume"] + x["askVolume"]).replace(0, np.nan)
    x["imbalance"] = ((x["bidVolume"] - x["askVolume"]) / denom).fillna(0.0)
    x["tick_move"] = np.sign(x["mid"].diff()).fillna(0.0)
    return x


def _minute_features(ticks: pd.DataFrame) -> pd.DataFrame:
    x = ticks.set_index("timestamp")
    out = x.resample("1min").agg(
        mid=("mid", "last"),
        spread=("spread", "mean"),
        imbalance=("imbalance", "mean"),
        imbalance_median=("imbalance", "median"),
        tick_move=("tick_move", "sum"),
        ticks=("mid", "size"),
        bid_volume=("bidVolume", "sum"),
        ask_volume=("askVolume", "sum"),
    ).dropna(subset=["mid"])
    out["mid_return"] = out["mid"].pct_change()
    out["imbalance_persist"] = out["imbalance"].rolling(3, min_periods=3).mean()
    out["tick_pressure"] = out["tick_move"].rolling(3, min_periods=3).sum()
    out["activity_z"] = out["ticks"].rolling(20, min_periods=20).apply(
        lambda a: (a[-1] - np.mean(a)) / (np.std(a) or 1.0), raw=True
    )
    out["spread_z"] = out["spread"].rolling(20, min_periods=20).apply(
        lambda a: (a[-1] - np.mean(a)) / (np.std(a) or 1.0), raw=True
    )
    return out.dropna()


def generate_tick_signal(ticks: pd.DataFrame) -> TickSignal:
    """Return BUY/SELL only when three microstructure conditions agree."""
    x = _clean(ticks)
    if len(x) < 300:
        return TickSignal("NO_TRADE", 0.0, "Insufficient tick history.")
    m = _minute_features(x)
    if len(m) < 25:
        return TickSignal("NO_TRADE", 0.0, "Insufficient completed 1m history.")

    r = m.iloc[-1]
    imb = float(r["imbalance"])
    persist = float(r["imbalance_persist"])
    pressure = float(r["tick_pressure"])
    activity_z = float(r["activity_z"])
    spread_z = float(r["spread_z"])

    buy_votes = int(imb >= 0.28) + int(persist >= 0.18) + int(pressure > 0)
    sell_votes = int(imb <= -0.28) + int(persist <= -0.18) + int(pressure < 0)
    spread_ok = spread_z < 2.5
    activity_ok = activity_z > -1.5

    if spread_ok and activity_ok and buy_votes >= 3:
        confidence = min(0.99, 0.50 + 0.08 * buy_votes + 0.04 * min(abs(imb), 1.0))
        return TickSignal("BUY", confidence, f"TickFlow BUY: imbalance={imb:.2f}, persistence={persist:.2f}, tick_pressure={pressure:.0f}, activity_z={activity_z:.2f}, spread_z={spread_z:.2f}.")
    if spread_ok and activity_ok and sell_votes >= 3:
        confidence = min(0.99, 0.50 + 0.08 * sell_votes + 0.04 * min(abs(imb), 1.0))
        return TickSignal("SELL", confidence, f"TickFlow SELL: imbalance={imb:.2f}, persistence={persist:.2f}, tick_pressure={pressure:.0f}, activity_z={activity_z:.2f}, spread_z={spread_z:.2f}.")
    return TickSignal("NO_TRADE", 0.0, f"TickFlow neutral: imbalance={imb:.2f}, persistence={persist:.2f}, tick_pressure={pressure:.0f}, activity_z={activity_z:.2f}, spread_z={spread_z:.2f}.")


def backtest_labels(ticks: pd.DataFrame, horizon_minutes: int = 1) -> pd.DataFrame:
    """Research helper: minute features plus a future midpoint-direction label."""
    x = _clean(ticks)
    m = _minute_features(x)
    if m.empty:
        return m
    m["future_mid"] = m["mid"].shift(-int(horizon_minutes))
    m["future_direction"] = np.sign(m["future_mid"] - m["mid"])
    return m
