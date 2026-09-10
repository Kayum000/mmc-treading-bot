"""Microprice Run Alignment strategy.

Latest version: v2.1
- 2-4 tick same-direction mid-price run
- microprice pressure threshold 0.40
- spread filter
- fast-tick confirmation (<200ms) when tick timestamps are available
- volume-weighted microprice when bid/ask volume exists
- quote-pressure fallback when Forex volume is unavailable

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
    # Keep the gap in milliseconds; BiQuote timestamps are UTC datetimes.
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
        # BiQuote Forex/CFD ticks do not provide bid/ask volume. Use the
        # observed price displacement as a quote-only pressure proxy.
        displacement = x["mid"].diff()
        x["microprice"] = x["mid"] + displacement
        x["micro_alignment"] = (
            displacement / x["spread"].replace(0, np.nan)
        ).clip(-1.0, 1.0)
        x["pressure_source"] = "quote-price pressure fallback"

    return x.dropna(subset=["mid", "direction"])


def _pip_multiplier(mid_price: float) -> float:
    return 100.0 if abs(float(mid_price)) >= 20.0 else 10000.0


def _confirmed_run(directions: np.ndarray) -> tuple[int, int] | None:
    """Return (run_length, direction) for the strongest current 2-4 tick run."""
    if len(directions) < 2:
        return None
    for length in (4, 3, 2):
        if len(directions) < length:
            continue
        run = directions[-length:]
        if np.all(run > 0):
            return length, 1
        if np.all(run < 0):
            return length, -1
    return None


def generate_signal(
    ticks: pd.DataFrame,
    run_length: int = 3,
    microprice_threshold: float = 0.40,
    max_spread_pips: float | None = None,
) -> TickRunSignal:
    x = _prepare(ticks)
    if len(x) < 5:
        return TickRunSignal("HOLD", 0.0, "insufficient tick history")

    # v2.1 honors the documented 2-4 tick validation zone. The supplied
    # run_length remains the preferred length when it is within that zone;
    # otherwise the strongest currently confirmed 2-4 tick run is used.
    preferred = int(np.clip(run_length, 2, 4))
    directions = x["direction"].to_numpy()
    run_info = None
    for length in (preferred, 4, 3, 2):
        if len(directions) < length:
            continue
        run = directions[-length:]
        if np.all(run > 0):
            run_info = (length, 1)
            break
        if np.all(run < 0):
            run_info = (length, -1)
            break
    if run_info is None:
        return TickRunSignal("HOLD", 0.0, "run confirmation absent")

    run_length_used, run_direction = run_info
    last = len(x) - 1
    mid = float(x.iloc[last]["mid"])
    pip_multiplier = _pip_multiplier(mid)
    spread_pips = float(x.iloc[last]["spread"] * pip_multiplier)

    if max_spread_pips is None:
        max_spread_pips = 2.5 if pip_multiplier == 100.0 else 1.5
    if spread_pips > max_spread_pips:
        return TickRunSignal("HOLD", 0.0, f"spread too wide ({spread_pips:.1f} pips)")

    micro = float(x.iloc[last]["micro_alignment"]) if not pd.isna(x.iloc[last]["micro_alignment"]) else np.nan
    if np.isnan(micro):
        return TickRunSignal("HOLD", 0.0, "quote pressure unavailable")

    gap = float(x.iloc[last]["tick_gap_ms"]) if not pd.isna(x.iloc[last]["tick_gap_ms"]) else np.nan
    fast_tick = not np.isnan(gap) and gap <= 200.0
    source = str(x.iloc[last]["pressure_source"])
    source_suffix = "" if source == "volume-weighted microprice" else "; quote-pressure fallback"

    if run_direction > 0 and micro >= microprice_threshold:
        confidence = 0.76 if fast_tick else 0.73
        if run_length_used == 2:
            confidence -= 0.02
        suffix = "; fast tick confirmation" if fast_tick else ""
        return TickRunSignal("BUY", confidence, f"{run_length_used}-tick upward run + pressure {micro:.2f}{source_suffix}{suffix}")

    if run_direction < 0 and micro <= -microprice_threshold:
        confidence = 0.78 if fast_tick else 0.74
        if run_length_used == 2:
            confidence -= 0.02
        suffix = "; fast tick confirmation" if fast_tick else ""
        return TickRunSignal("SELL", confidence, f"{run_length_used}-tick downward run + pressure {micro:.2f}{source_suffix}{suffix}")

    return TickRunSignal("HOLD", 0.0, "run and pressure are not aligned")


def backtest_labels(
    ticks: pd.DataFrame,
    run_length: int = 3,
    microprice_threshold: float = 0.40,
) -> pd.DataFrame:
    x = _prepare(ticks)
    x["signal"] = "HOLD"
    d = x["direction"].to_numpy()
    preferred = int(np.clip(run_length, 2, 4))

    for i in range(2, len(x) - 1):
        found = None
        for length in (preferred, 4, 3, 2):
            if i + 1 < length:
                continue
            run = d[i-length+1:i+1]
            if np.all(run > 0):
                found = 1
                break
            if np.all(run < 0):
                found = -1
                break
        if found is None:
            continue
        micro = x.iloc[i]["micro_alignment"]
        if pd.isna(micro):
            continue
        if found > 0 and micro >= microprice_threshold:
            x.iat[i, x.columns.get_loc("signal")] = "BUY"
        elif found < 0 and micro <= -microprice_threshold:
            x.iat[i, x.columns.get_loc("signal")] = "SELL"

    x["future_direction"] = np.sign(x["mid"].shift(-1) - x["mid"])
    x["correct"] = (
        ((x.signal == "BUY") & (x.future_direction > 0))
        | ((x.signal == "SELL") & (x.future_direction < 0))
    )
    return x
