"""Tick-Run Pressure Continuation strategy.

The only live entry logic for the bot. Previous MMC / MTF / candle strategies
are intentionally not used here.

Primary research mode (Dukascopy-style tick files):
- 8 consecutive same-direction mid-price ticks
- strong bid/ask volume imbalance confirmation

Live broker mode:
- the public BiQuote FX feed exposes bid/ask/mid but not bid/ask traded volume
- therefore live mode uses the same 8-tick run plus an instrument-aware
  spread-quality filter; it never invents volume data.
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
    required = {"timestamp", "askPrice", "bidPrice"}
    missing = required - set(ticks.columns)
    if missing:
        raise ValueError(f"missing tick columns: {sorted(missing)}")
    x = ticks.copy()
    for c in ["askPrice", "bidPrice"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    x["mid"] = (x["askPrice"] + x["bidPrice"]) / 2.0
    x["spread"] = x["askPrice"] - x["bidPrice"]
    x["direction"] = np.sign(x["mid"].diff()).fillna(0)
    if {"askVolume", "bidVolume"}.issubset(x.columns):
        x["askVolume"] = pd.to_numeric(x["askVolume"], errors="coerce")
        x["bidVolume"] = pd.to_numeric(x["bidVolume"], errors="coerce")
        total = x["bidVolume"] + x["askVolume"]
        x["imbalance"] = (x["bidVolume"] - x["askVolume"]) / total.replace(0, np.nan)
    else:
        x["imbalance"] = np.nan
    return x.dropna(subset=["mid", "direction"])


def _pip_multiplier(mid_price: float) -> float:
    """Convert quote-price distance to standard FX pips.

    JPY crosses use 0.01 per pip; most other FX pairs use 0.0001.
    """
    return 100.0 if abs(float(mid_price)) >= 20.0 else 10000.0


def generate_signal(
    ticks: pd.DataFrame,
    run_length: int = 8,
    imbalance_threshold: float = 0.60,
    max_spread_pips: float | None = None,
) -> TickRunSignal:
    x = _prepare(ticks)
    if len(x) < run_length + 2:
        return TickRunSignal("HOLD", 0.0, "insufficient tick history")

    d = x["direction"].to_numpy()
    last = len(x) - 1
    run = d[last - run_length + 1:last + 1]
    mid = float(x.iloc[last]["mid"])
    pip_multiplier = _pip_multiplier(mid)
    spread_pips = float(x.iloc[last]["spread"] * pip_multiplier)

    # Default limits are deliberately instrument-aware. The old fixed
    # 1.5-pip rule was too strict for JPY crosses such as GBPJPY.
    if max_spread_pips is None:
        max_spread_pips = 2.5 if pip_multiplier == 100.0 else 1.5

    if spread_pips > max_spread_pips:
        return TickRunSignal("HOLD", 0.0, f"spread too wide ({spread_pips:.1f} pips)")

    has_volume = not pd.isna(x.iloc[last]["imbalance"])
    if has_volume:
        imb = float(x.iloc[last]["imbalance"])
        if np.all(run > 0) and imb >= imbalance_threshold:
            conf = min(0.99, 0.70 + 0.20 * (imb - imbalance_threshold) / (1.0 - imbalance_threshold))
            return TickRunSignal("BUY", conf, f"{run_length}-tick upward run + strong bid-volume pressure")
        if np.all(run < 0) and imb <= -imbalance_threshold:
            conf = min(0.99, 0.70 + 0.20 * ((-imb) - imbalance_threshold) / (1.0 - imbalance_threshold))
            return TickRunSignal("SELL", conf, f"{run_length}-tick downward run + strong ask-volume pressure")
    else:
        if np.all(run > 0):
            return TickRunSignal("BUY", 0.70, f"{run_length}-tick upward run; live quote-volume unavailable")
        if np.all(run < 0):
            return TickRunSignal("SELL", 0.70, f"{run_length}-tick downward run; live quote-volume unavailable")

    return TickRunSignal("HOLD", 0.0, "run confirmation absent")


def backtest_labels(ticks: pd.DataFrame, run_length: int = 8, imbalance_threshold: float = 0.60) -> pd.DataFrame:
    x = _prepare(ticks)
    x["signal"] = "HOLD"
    d = x["direction"].to_numpy()
    has_volume = not x["imbalance"].isna().all()
    for i in range(run_length, len(x) - 1):
        run = d[i-run_length+1:i+1]
        if not np.all(run > 0) and not np.all(run < 0):
            continue
        if has_volume:
            imb = x.iloc[i]["imbalance"]
            if np.all(run > 0) and imb >= imbalance_threshold:
                x.iat[i, x.columns.get_loc("signal")] = "BUY"
            elif np.all(run < 0) and imb <= -imbalance_threshold:
                x.iat[i, x.columns.get_loc("signal")] = "SELL"
        else:
            x.iat[i, x.columns.get_loc("signal")] = "BUY" if np.all(run > 0) else "SELL"
    x["future_direction"] = np.sign(x["mid"].shift(-1) - x["mid"])
    x["correct"] = ((x.signal == "BUY") & (x.future_direction > 0)) | ((x.signal == "SELL") & (x.future_direction < 0))
    return x
