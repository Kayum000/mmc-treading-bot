"""Liquidity Response strategy.

New microstructure-only idea:
- Detect a short-lived liquidity pressure shock from bid/ask volume changes.
- Measure whether price responds to that pressure or fails to respond.
- Pressure + matching price response => continuation.
- Strong pressure + weak/opposite price response => exhaustion/reversal.
No MMC, sweep, MSS, MTF, S/R, ORB, candle-pattern or TickFlow rules are used.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class LRSignal:
    action: str
    confidence: float
    reason: str


def _clean(ticks: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "askPrice", "bidPrice", "askVolume", "bidVolume"}
    missing = required - set(ticks.columns)
    if missing:
        raise ValueError(f"missing tick columns: {sorted(missing)}")
    x = ticks.copy()
    x["ts"] = pd.to_datetime(x["timestamp"], unit="ms", utc=True)
    for c in ["askPrice", "bidPrice", "askVolume", "bidVolume"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=["ts", "askPrice", "bidPrice", "askVolume", "bidVolume"])
    x = x.sort_values("ts").drop_duplicates("ts")
    x["mid"] = (x["askPrice"] + x["bidPrice"]) / 2.0
    x["spread"] = x["askPrice"] - x["bidPrice"]
    total = x["askVolume"] + x["bidVolume"]
    x["imb"] = (x["bidVolume"] - x["askVolume"]) / total.replace(0, np.nan)
    x["dt_s"] = x["ts"].diff().dt.total_seconds().clip(lower=0.001, upper=10)
    x["tick_dir"] = np.sign(x["mid"].diff()).fillna(0)
    return x.dropna(subset=["imb"])


def minute_features(ticks: pd.DataFrame) -> pd.DataFrame:
    x = _clean(ticks).set_index("ts")
    # Aggregate microstructure state, not OHLC/candle patterns.
    g = x.resample("1min")
    m = pd.DataFrame(index=g.size().index)
    m["mid"] = g["mid"].last()
    m["mid_prev"] = m["mid"].shift(1)
    m["ret"] = m["mid"].pct_change()
    m["imb_mean"] = g["imb"].mean()
    m["imb_last"] = g["imb"].last()
    m["imb_q90"] = g["imb"].quantile(0.90)
    m["imb_q10"] = g["imb"].quantile(0.10)
    m["bid_vol"] = g["bidVolume"].sum()
    m["ask_vol"] = g["askVolume"].sum()
    m["spread_mean"] = g["spread"].mean()
    m["ticks"] = g.size()
    m["up_ticks"] = g["tick_dir"].apply(lambda s: (s > 0).sum())
    m["down_ticks"] = g["tick_dir"].apply(lambda s: (s < 0).sum())

    # Pressure change: acceleration of liquidity imbalance.
    m["pressure_delta"] = m["imb_mean"].diff()
    m["pressure_accel"] = m["pressure_delta"].diff()
    # Price response to pressure: same minute return normalized by recent activity.
    ret_scale = m["ret"].rolling(10, min_periods=5).std()
    m["ret_z"] = m["ret"] / ret_scale.replace(0, np.nan)
    m["response"] = m["ret_z"] * m["pressure_delta"]
    # Failure-to-respond score: large pressure with unusually small price response.
    m["abs_pressure"] = m["pressure_delta"].abs()
    m["abs_response"] = m["ret_z"].abs()
    m["failure"] = m["abs_pressure"] / (m["abs_response"] + 0.15)
    # Activity regime and spread regime are used only as quality filters.
    tick_mean = m["ticks"].rolling(30, min_periods=10).mean()
    tick_std = m["ticks"].rolling(30, min_periods=10).std()
    m["activity_z"] = (m["ticks"] - tick_mean) / tick_std.replace(0, np.nan)
    sp_mean = m["spread_mean"].rolling(30, min_periods=10).mean()
    sp_std = m["spread_mean"].rolling(30, min_periods=10).std()
    m["spread_z"] = (m["spread_mean"] - sp_mean) / sp_std.replace(0, np.nan)
    # Persistence of pressure across the previous three minutes.
    m["pressure_3"] = m["imb_mean"].rolling(3).mean()
    m["pressure_change_3"] = m["pressure_delta"].rolling(3).sum()
    return m.dropna()


def generate_signal(ticks: pd.DataFrame) -> LRSignal:
    m = minute_features(ticks)
    if len(m) < 40:
        return LRSignal("HOLD", 0.0, "insufficient microstructure history")
    r = m.iloc[-1]
    pressure = float(r["pressure_change_3"])
    response = float(r["ret_z"])
    failure = float(r["failure"])
    activity = float(r["activity_z"])
    spread_z = float(r["spread_z"])

    # Continuation: pressure and price response agree.
    if pressure >= 0.20 and response > 0.25 and activity > -1.0 and spread_z < 2.0:
        conf = min(0.99, 0.55 + 0.18 * min(2, pressure) + 0.08 * min(2, response))
        return LRSignal("BUY", conf, "positive liquidity pressure confirmed by price response")
    if pressure <= -0.20 and response < -0.25 and activity > -1.0 and spread_z < 2.0:
        conf = min(0.99, 0.55 + 0.18 * min(2, -pressure) + 0.08 * min(2, -response))
        return LRSignal("SELL", conf, "negative liquidity pressure confirmed by price response")

    # Exhaustion: strong pressure but price fails to follow, then use the response sign
    # as the reversal direction. This is intentionally different from raw imbalance.
    if failure > 0.65 and abs(pressure) >= 0.20 and activity > -1.0 and spread_z < 2.0:
        if pressure > 0 and response <= 0:
            return LRSignal("SELL", 0.60, "buy-side pressure failed to lift price")
        if pressure < 0 and response >= 0:
            return LRSignal("BUY", 0.60, "sell-side pressure failed to lower price")

    return LRSignal("HOLD", 0.0, "no pressure-response alignment")


def label_future(m: pd.DataFrame, horizon: int = 3) -> pd.DataFrame:
    out = m.copy()
    out["future_ret"] = out["mid"].shift(-horizon) / out["mid"] - 1.0
    out["label"] = np.sign(out["future_ret"])
    return out
