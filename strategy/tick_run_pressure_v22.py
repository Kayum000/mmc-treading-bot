"""Microprice Run Alignment strategy v2.2.

v2.2 keeps the v2.1 tick-run core but adds two quality filters:
- short-window directional momentum agreement
- directional efficiency (movement vs. tick noise)

The existing v2.1 implementation remains untouched in tick_run_pressure.py.
This module is intentionally tick-based and does not use MMC, MTF, S/R,
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
        x["pressure_source"] = "volume-weighted microprice"
    else:
        # Forex feeds commonly lack bid/ask volume. Preserve the v2.1
        # quote-pressure proxy, but v2.2 requires stronger confirmation below.
        displacement = x["mid"].diff()
        x["microprice"] = x["mid"] + displacement
        x["micro_alignment"] = (
            displacement / x["spread"].replace(0, np.nan)
        ).clip(-1.0, 1.0)
        x["pressure_source"] = "quote-price pressure fallback"

    return x.dropna(subset=["mid", "direction"])


def _pip_multiplier(mid_price: float) -> float:
    return 100.0 if abs(float(mid_price)) >= 20.0 else 10000.0


def _run(directions: np.ndarray, preferred: int) -> tuple[int, int] | None:
    for length in (preferred, 4, 3):
        if len(directions) < length:
            continue
        current = directions[-length:]
        if np.all(current > 0):
            return length, 1
        if np.all(current < 0):
            return length, -1
    return None


def _window_stats(x: pd.DataFrame, seconds: float) -> tuple[float, float]:
    """Return (net movement, directional efficiency) for the latest window."""
    if len(x) < 3:
        return np.nan, np.nan
    end = x.iloc[-1]["timestamp"]
    start = end - pd.Timedelta(seconds=seconds)
    w = x[x["timestamp"] >= start]
    if len(w) < 3:
        return np.nan, np.nan
    values = w["mid"].to_numpy(dtype=float)
    diffs = np.diff(values)
    net = float(values[-1] - values[0])
    noise = float(np.abs(diffs).sum())
    efficiency = abs(net) / noise if noise > 0 else 0.0
    return net, efficiency


def generate_signal(
    ticks: pd.DataFrame,
    run_length: int = 3,
    microprice_threshold: float = 0.50,
    max_spread_pips: float | None = None,
    min_efficiency: float = 0.30,
) -> TickRunSignal:
    x = _prepare(ticks)
    if len(x) < 8:
        return TickRunSignal("HOLD", 0.0, "পর্যাপ্ত tick history নেই")

    preferred = int(np.clip(run_length, 3, 4))
    run_info = _run(x["direction"].to_numpy(), preferred)
    if run_info is None:
        return TickRunSignal("HOLD", 0.0, "tick-run confirmation পাওয়া যায়নি")

    run_length_used, run_direction = run_info
    last = x.iloc[-1]
    mid = float(last["mid"])
    pip_multiplier = _pip_multiplier(mid)
    spread_pips = float(last["spread"] * pip_multiplier)
    if max_spread_pips is None:
        max_spread_pips = 1.5 if pip_multiplier == 10000.0 else 2.5
    if spread_pips > max_spread_pips:
        return TickRunSignal("HOLD", 0.0, f"spread বেশি ({spread_pips:.1f} pips)")

    micro = float(last["micro_alignment"]) if not pd.isna(last["micro_alignment"]) else np.nan
    if np.isnan(micro):
        return TickRunSignal("HOLD", 0.0, "quote pressure পাওয়া যায়নি")

    momentum_5s, _ = _window_stats(x, 5.0)
    _, efficiency_10s = _window_stats(x, 10.0)
    if np.isnan(momentum_5s) or np.isnan(efficiency_10s):
        return TickRunSignal("HOLD", 0.0, "স্বল্প-মেয়াদি momentum confirmation পাওয়া যায়নি")

    momentum_direction = int(np.sign(momentum_5s))
    if momentum_direction != run_direction:
        return TickRunSignal("HOLD", 0.0, "tick run ও 5-second momentum একই দিকে নেই")
    if efficiency_10s < min_efficiency:
        return TickRunSignal("HOLD", 0.0, f"দিকনির্দেশের শক্তি কম (efficiency {efficiency_10s:.2f})")

    gap = float(last["tick_gap_ms"]) if not pd.isna(last["tick_gap_ms"]) else np.nan
    if np.isnan(gap) or gap > 200.0:
        return TickRunSignal("HOLD", 0.0, "fast-tick confirmation পাওয়া যায়নি")

    source = str(last["pressure_source"])
    if run_direction > 0 and micro >= microprice_threshold:
        confidence = 0.80 if run_length_used >= 4 else 0.78
        return TickRunSignal(
            "BUY", confidence,
            f"{run_length_used}-tick upward run + pressure {micro:.2f}; 5s momentum aligned; efficiency {efficiency_10s:.2f}; fast tick"
        )
    if run_direction < 0 and micro <= -microprice_threshold:
        confidence = 0.82 if run_length_used >= 4 else 0.80
        return TickRunSignal(
            "SELL", confidence,
            f"{run_length_used}-tick downward run + pressure {micro:.2f}; 5s momentum aligned; efficiency {efficiency_10s:.2f}; fast tick"
        )

    return TickRunSignal("HOLD", 0.0, "tick run ও pressure একই দিকে যথেষ্ট শক্তিশালী নয়")
