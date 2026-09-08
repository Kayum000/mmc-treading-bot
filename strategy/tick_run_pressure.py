"""Microprice Run Alignment strategy.

Latest version: v2.0
- 2-4 tick same-direction mid-price run
- microprice pressure threshold 0.40
- spread filter
- fast-tick confirmation (<200ms) when tick timestamps are available
- volume-weighted microprice when bid/ask volume exists

The strategy is intentionally tick-based and does not use MMC, MTF, S/R,
ORB, candles, EMA, RSI or MACD.
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
    for c in ["askPrice", "bidPrice", "timestamp"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    x["mid"] = (x["askPrice"] + x["bidPrice"]) / 2.0
    x["spread"] = x["askPrice"] - x["bidPrice"]
    x["direction"] = np.sign(x["mid"].diff()).fillna(0)
    x["tick_gap_ms"] = x["timestamp"].diff()

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
    if len(x) < 5:
        return TickRunSignal("HOLD", 0.0, "insufficient tick history")

    # v2 uses the strongest validated run zone: 2-4 ticks.
    run_length = int(np.clip(run_length, 2, 4))
    last = len(x) - 1
    run = x["direction"].to_numpy()[last - run_length + 1:last + 1]
    mid = float(x.iloc[last]["mid"])
    pip_multiplier = _pip_multiplier(mid)
    spread_pips = float(x.iloc[last]["spread"] * pip_multiplier)

    if max_spread_pips is None:
        max_spread_pips = 2.5 if pip_multiplier == 100.0 else 1.5
    if spread_pips > max_spread_pips:
        return TickRunSignal("HOLD", 0.0, f"spread too wide ({spread_pips:.1f} pips)")

    if not np.all(run > 0) and not np.all(run < 0):
        return TickRunSignal("HOLD", 0.0, "run confirmation absent")

    micro = float(x.iloc[last]["micro_alignment"]) if not pd.isna(x.iloc[last]["micro_alignment"]) else np.nan
    if np.isnan(micro):
        return TickRunSignal("HOLD", 0.0, "microprice volume unavailable")

    # The edge is strongest when the market is updating quickly.
    gap = float(x.iloc[last]["tick_gap_ms"]) if not pd.isna(x.iloc[last]["tick_gap_ms"]) else np.nan
    fast_tick = not np.isnan(gap) and gap <= 200.0

    if np.all(run > 0) and micro >= microprice_threshold:
        confidence = 0.76 if fast_tick else 0.73
        suffix = "; fast tick confirmation" if fast_tick else ""
        return TickRunSignal("BUY", confidence, f"{run_length}-tick upward run + microprice pressure {micro:.2f}{suffix}")

    if np.all(run < 0) and micro <= -microprice_threshold:
        confidence = 0.78 if fast_tick else 0.74
        suffix = "; fast tick confirmation" if fast_tick else ""
        return TickRunSignal("SELL", confidence, f"{run_length}-tick downward run + microprice pressure {micro:.2f}{suffix}")

    return TickRunSignal("HOLD", 0.0, "run and microprice pressure are not aligned")


def backtest_labels(
    ticks: pd.DataFrame,
    run_length: int = 3,
    microprice_threshold: float = 0.40,
) -> pd.DataFrame:
    x = _prepare(ticks)
    x["signal"] = "HOLD"
    d = x["direction"].to_numpy()
    run_length = int(np.clip(run_length, 2, 4))

    for i in range(run_length, len(x) - 1):
        run = d[i-run_length+1:i+1]
        if not np.all(run > 0) and not np.all(run < 0):
            continue
        micro = x.iloc[i]["micro_alignment"]
        if pd.isna(micro):
            continue
        gap = x.iloc[i]["tick_gap_ms"]
        # Fast-tick confirmation is used only as a quality flag, not a mandatory
        # historical filter, so the backtest remains comparable with v1.
        if np.all(run > 0) and micro >= microprice_threshold:
            x.iat[i, x.columns.get_loc("signal")] = "BUY"
        elif np.all(run < 0) and micro <= -microprice_threshold:
            x.iat[i, x.columns.get_loc("signal")] = "SELL"

    x["future_direction"] = np.sign(x["mid"].shift(-1) - x["mid"])
    x["correct"] = (
        ((x.signal == "BUY") & (x.future_direction > 0))
        | ((x.signal == "SELL") & (x.future_direction < 0))
    )
    return x
