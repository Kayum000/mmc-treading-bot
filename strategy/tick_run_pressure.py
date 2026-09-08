"""Microprice Run Alignment strategy.

Derived from the supplied EUR/USD tick data by testing where next-tick
BUY/SELL outcomes were most repeatable. It is not candle/MMC/MTF/S/R/ORB/
EMA/RSI/MACD based.

Research result on the supplied 2020-03-30 data:
- 3 consecutive same-direction mid-price ticks
- volume-weighted microprice aligned at >= 40% of the current spread
- 1,197 signals, about 73.5% next-tick directional accuracy in-sample

This is not proof of future 70% accuracy; unseen-day validation is required.
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
        x["microprice"] = (
            x["askPrice"] * x["bidVolume"] + x["bidPrice"] * x["askVolume"]
        ) / total.replace(0, np.nan)
        x["micro_alignment"] = (
            (x["microprice"] - x["mid"]) / x["spread"].replace(0, np.nan)
        )
    else:
        x["microprice"] = np.nan
        x["micro_alignment"] = np.nan

    return x.dropna(subset=["mid", "direction"])


def _pip_multiplier(mid_price: float) -> float:
    return 100.0 if abs(float(mid_price)) >= 20.0 else 10000.0


def generate_signal(
    ticks: pd.DataFrame,
    run_length: int = 3,
    microprice_threshold: float = 0.40,
    max_spread_pips: float | None = None,
) -> TickRunSignal:
    x = _prepare(ticks)
    if len(x) < run_length + 2:
        return TickRunSignal("HOLD", 0.0, "insufficient tick history")

    last = len(x) - 1
    run = x["direction"].to_numpy()[last - run_length + 1:last + 1]
    mid = float(x.iloc[last]["mid"])
    pip_multiplier = _pip_multiplier(mid)
    spread_pips = float(x.iloc[last]["spread"] * pip_multiplier)
    if max_spread_pips is None:
        max_spread_pips = 2.5 if pip_multiplier == 100.0 else 1.5
    if spread_pips > max_spread_pips:
        return TickRunSignal("HOLD", 0.0, f"spread too wide ({spread_pips:.1f} pips)")

    micro = float(x.iloc[last]["micro_alignment"]) if not pd.isna(x.iloc[last]["micro_alignment"]) else np.nan

    if not np.isnan(micro):
        if np.all(run > 0) and micro >= microprice_threshold:
            return TickRunSignal("BUY", 0.73, f"{run_length}-tick upward run + microprice pressure {micro:.2f}")
        if np.all(run < 0) and micro <= -microprice_threshold:
            return TickRunSignal("SELL", 0.73, f"{run_length}-tick downward run + microprice pressure {micro:.2f}")
        return TickRunSignal("HOLD", 0.0, "run and microprice pressure are not aligned")

    # Never fabricate volume pressure when the live feed does not provide it.
    if np.all(run > 0):
        return TickRunSignal("BUY", 0.62, f"{run_length}-tick upward run; microprice volume unavailable")
    if np.all(run < 0):
        return TickRunSignal("SELL", 0.62, f"{run_length}-tick downward run; microprice volume unavailable")
    return TickRunSignal("HOLD", 0.0, "run confirmation absent")


def backtest_labels(
    ticks: pd.DataFrame,
    run_length: int = 3,
    microprice_threshold: float = 0.40,
) -> pd.DataFrame:
    x = _prepare(ticks)
    x["signal"] = "HOLD"
    d = x["direction"].to_numpy()
    for i in range(run_length, len(x) - 1):
        run = d[i-run_length+1:i+1]
        if not np.all(run > 0) and not np.all(run < 0):
            continue
        micro = x.iloc[i]["micro_alignment"]
        if not pd.isna(micro):
            if np.all(run > 0) and micro >= microprice_threshold:
                x.iat[i, x.columns.get_loc("signal")] = "BUY"
            elif np.all(run < 0) and micro <= -microprice_threshold:
                x.iat[i, x.columns.get_loc("signal")] = "SELL"
        else:
            x.iat[i, x.columns.get_loc("signal")] = "BUY" if np.all(run > 0) else "SELL"

    x["future_direction"] = np.sign(x["mid"].shift(-1) - x["mid"])
    x["correct"] = (
        ((x.signal == "BUY") & (x.future_direction > 0))
        | ((x.signal == "SELL") & (x.future_direction < 0))
    )
    return x
