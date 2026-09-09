"""Microprice Run Alignment strategy.

Latest version: v2.1
- 2-4 tick same-direction mid-price run
- microprice pressure threshold 0.40 when bid/ask volume is available
- spread filter
- fast-tick confirmation as a confidence boost
- safe quote-run fallback when the live feed has no volume fields

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
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    for c in ["askPrice", "bidPrice"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    x["mid"] = (x["askPrice"] + x["bidPrice"]) / 2.0
    x["spread"] = x["askPrice"] - x["bidPrice"]
    x["direction"] = np.sign(x["mid"].diff()).fillna(0)
    x["tick_gap_ms"] = x["timestamp"].diff().dt.total_seconds() * 1000.0

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


def _run_action(directions: np.ndarray, run_length: int) -> str:
    if len(directions) < run_length:
        return "HOLD"
    run = directions[-run_length:]
    if np.all(run > 0):
        return "BUY"
    if np.all(run < 0):
        return "SELL"
    return "HOLD"


def generate_signal(
    ticks: pd.DataFrame,
    run_length: int = 3,
    microprice_threshold: float = 0.40,
    max_spread_pips: float | None = None,
) -> TickRunSignal:
    x = _prepare(ticks)
    if len(x) < 5:
        return TickRunSignal("HOLD", 0.0, "insufficient tick history")

    run_length = int(np.clip(run_length, 2, 4))
    last = len(x) - 1
    mid = float(x.iloc[last]["mid"])
    pip_multiplier = _pip_multiplier(mid)
    spread_pips = float(x.iloc[last]["spread"] * pip_multiplier)

    if max_spread_pips is None:
        max_spread_pips = 2.5 if pip_multiplier == 100.0 else 1.5
    if spread_pips > max_spread_pips:
        return TickRunSignal("HOLD", 0.0, f"spread too wide ({spread_pips:.1f} pips)")

    directions = x["direction"].to_numpy()
    action = _run_action(directions, run_length)
    if action == "HOLD":
        return TickRunSignal("HOLD", 0.0, "run confirmation absent")

    micro = float(x.iloc[last]["micro_alignment"]) if not pd.isna(x.iloc[last]["micro_alignment"]) else np.nan
    gap = float(x.iloc[last]["tick_gap_ms"]) if not pd.isna(x.iloc[last]["tick_gap_ms"]) else np.nan
    fast_tick = not np.isnan(gap) and gap <= 200.0

    if not np.isnan(micro):
        if action == "BUY" and micro >= microprice_threshold:
            confidence = 0.76 if fast_tick else 0.73
            suffix = "; fast tick confirmation" if fast_tick else ""
            return TickRunSignal("BUY", confidence, f"{run_length}-tick upward run + microprice pressure {micro:.2f}{suffix}")
        if action == "SELL" and micro <= -microprice_threshold:
            confidence = 0.78 if fast_tick else 0.74
            suffix = "; fast tick confirmation" if fast_tick else ""
            return TickRunSignal("SELL", confidence, f"{run_length}-tick downward run + microprice pressure {micro:.2f}{suffix}")
        return TickRunSignal("HOLD", 0.0, "run and microprice pressure are not aligned")

    # BiQuote's documented FX feed has no usable real volume fields.
    # Keep the bot live instead of forcing HOLD forever when volume is absent.
    fallback_conf = 0.64 if fast_tick else 0.62
    suffix = "; fast tick" if fast_tick else ""
    direction_text = "upward" if action == "BUY" else "downward"
    return TickRunSignal(
        action,
        fallback_conf,
        f"{run_length}-tick {direction_text} quote run; microprice volume unavailable{suffix}",
    )


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
            x.iat[i, x.columns.get_loc("signal")] = "BUY" if np.all(run > 0) else "SELL"
        elif np.all(run > 0) and micro >= microprice_threshold:
            x.iat[i, x.columns.get_loc("signal")] = "BUY"
        elif np.all(run < 0) and micro <= -microprice_threshold:
            x.iat[i, x.columns.get_loc("signal")] = "SELL"

    x["future_direction"] = np.sign(x["mid"].shift(-1) - x["mid"])
    x["correct"] = (
        ((x.signal == "BUY") & (x.future_direction > 0))
        | ((x.signal == "SELL") & (x.future_direction < 0))
    )
    return x
