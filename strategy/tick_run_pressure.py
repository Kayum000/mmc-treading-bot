"""Quote Displacement Continuation strategy.

v3.0 — built from the April 1-7 EURUSD tick study.

The original tick strategy is kept intact. A separate candle adapter below
applies the same core rule to completed 1-minute candles:
- at least 2 consecutive same-direction candles;
- 5-candle close displacement >= 7 pips in the same direction.
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


def _pip_multiplier(mid_price: float) -> float:
    return 100.0 if abs(float(mid_price)) >= 20.0 else 10000.0


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

    directions = x["direction"].to_numpy()
    run = np.zeros(len(x), dtype=int)
    previous = 0.0
    length = 0
    for i, value in enumerate(directions):
        if value == 0:
            length = 0
            previous = 0.0
        elif value == previous:
            length += 1
        else:
            length = 1
        run[i] = int(length * (1 if value > 0 else -1)) if value != 0 else 0
        previous = value
    x["run"] = run

    multiplier = x["mid"].map(_pip_multiplier)
    x["displacement_5"] = x["mid"].diff(5) * multiplier
    return x


def generate_signal(
    ticks: pd.DataFrame,
    min_run_length: int = 2,
    displacement_pips: float = 7.0,
    max_spread_pips: float | None = None,
) -> TickRunSignal:
    x = _prepare(ticks)
    if len(x) < 10:
        return TickRunSignal("HOLD", 0.0, "insufficient tick history")

    last = x.iloc[-1]
    mid = float(last["mid"])
    pip_multiplier = _pip_multiplier(mid)
    spread_pips = float(last["spread"] * pip_multiplier)

    if max_spread_pips is None:
        max_spread_pips = 2.5 if pip_multiplier == 100.0 else 1.5
    if spread_pips > max_spread_pips:
        return TickRunSignal("HOLD", 0.0, f"spread too wide ({spread_pips:.1f} pips)")

    run = int(last["run"])
    displacement = float(last["displacement_5"])
    if not np.isfinite(displacement):
        return TickRunSignal("HOLD", 0.0, "five-tick displacement unavailable")

    run_direction = np.sign(run)
    displacement_direction = np.sign(displacement)
    if abs(run) < int(min_run_length):
        return TickRunSignal("HOLD", 0.0, "short tick-run confirmation absent")
    if abs(displacement) < float(displacement_pips):
        return TickRunSignal("HOLD", 0.0, "five-tick displacement below threshold")
    if run_direction != displacement_direction:
        return TickRunSignal("HOLD", 0.0, "tick run and displacement disagree")

    action = "BUY" if run_direction > 0 else "SELL"
    confidence = 0.67
    direction_text = "upward" if action == "BUY" else "downward"
    return TickRunSignal(
        action,
        confidence,
        f"{abs(run)}-tick {direction_text} run + {abs(displacement):.1f}-pip 5-tick displacement",
    )


def generate_candle_signal(
    candles: pd.DataFrame,
    min_run_length: int = 2,
    displacement_pips: float = 7.0,
) -> TickRunSignal:
    """Apply the same signal rule to completed 1-minute OHLC candles."""
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(candles.columns)
    if missing:
        raise ValueError(f"missing candle columns: {sorted(missing)}")

    x = candles.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    for c in ["open", "high", "low", "close"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    if len(x) < 10:
        return TickRunSignal("HOLD", 0.0, "insufficient 1-minute candle history")

    # Candle direction is determined by close vs open. Doji candles reset the run.
    x["direction"] = np.sign(x["close"] - x["open"])
    directions = x["direction"].to_numpy()
    run = np.zeros(len(x), dtype=int)
    previous = 0.0
    length = 0
    for i, value in enumerate(directions):
        if value == 0:
            length = 0
            previous = 0.0
        elif value == previous:
            length += 1
        else:
            length = 1
        run[i] = int(length * (1 if value > 0 else -1)) if value != 0 else 0
        previous = value
    x["run"] = run

    multiplier = _pip_multiplier(float(x.iloc[-1]["close"]))
    x["displacement_5"] = x["close"].diff(5) * multiplier

    last = x.iloc[-1]
    run_value = int(last["run"])
    displacement = float(last["displacement_5"])
    if not np.isfinite(displacement):
        return TickRunSignal("HOLD", 0.0, "five-candle displacement unavailable")

    run_direction = np.sign(run_value)
    displacement_direction = np.sign(displacement)
    if abs(run_value) < int(min_run_length):
        return TickRunSignal("HOLD", 0.0, "short candle-run confirmation absent")
    if abs(displacement) < float(displacement_pips):
        return TickRunSignal("HOLD", 0.0, "five-candle displacement below threshold")
    if run_direction != displacement_direction:
        return TickRunSignal("HOLD", 0.0, "candle run and displacement disagree")

    action = "BUY" if run_direction > 0 else "SELL"
    direction_text = "upward" if action == "BUY" else "downward"
    return TickRunSignal(
        action,
        0.67,
        f"{abs(run_value)}-candle {direction_text} run + {abs(displacement):.1f}-pip 5-candle displacement",
    )


def backtest_labels(
    ticks: pd.DataFrame,
    min_run_length: int = 2,
    displacement_pips: float = 7.0,
) -> pd.DataFrame:
    x = _prepare(ticks)
    x["signal"] = "HOLD"
    valid = (
        (x["run"].abs() >= int(min_run_length))
        & (x["displacement_5"].abs() >= float(displacement_pips))
        & (np.sign(x["run"]) == np.sign(x["displacement_5"]))
    )
    x.loc[valid & (x["run"] > 0), "signal"] = "BUY"
    x.loc[valid & (x["run"] < 0), "signal"] = "SELL"
    x["future_direction"] = np.sign(x["mid"].shift(-1) - x["mid"])
    x["correct"] = (
        ((x.signal == "BUY") & (x.future_direction > 0))
        | ((x.signal == "SELL") & (x.future_direction < 0))
    )
    return x
