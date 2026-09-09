"""3-minute Extreme Rejection strategy.

Research candidate derived from the 2020-04-01 through 2020-04-07 EURUSD
quote-only tick sample.

Core idea:
1. Build completed 3-minute mid-price candles.
2. Compare the completed candle's range with the median range of the
   previous 30 completed 3-minute candles.
3. Only act when the current range is >= 2x that local baseline.
4. If the candle closes near its high (>= 70% of its range), signal SELL.
5. If it closes near its low (<= 30% of its range), signal BUY.
6. The signal is a rejection/reversal setup, not momentum continuation.

This is intentionally separate from the existing tick-run strategy and is
NOT wired into the live signal path by this file alone.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class ExtremeRejectionSignal:
    action: str
    confidence: float
    reason: str
    candle_time: str | None = None


def _prepare(ticks: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "askPrice", "bidPrice"}
    missing = required - set(ticks.columns)
    if missing:
        raise ValueError(f"missing tick columns: {sorted(missing)}")

    x = ticks.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    for col in ["askPrice", "bidPrice"]:
        x[col] = pd.to_numeric(x[col], errors="coerce")
    x = (
        x.dropna(subset=list(required))
        .sort_values("timestamp")
        .drop_duplicates("timestamp")
    )
    x["mid"] = (x["askPrice"] + x["bidPrice"]) / 2.0
    return x[["timestamp", "mid"]]


def _candles(ticks: pd.DataFrame) -> pd.DataFrame:
    x = _prepare(ticks).set_index("timestamp")
    candles = x["mid"].resample("3min").ohlc().dropna()
    candles["range"] = candles["high"] - candles["low"]
    candles["range_pips"] = candles["range"] * 10000.0
    candles["close_location"] = (
        (candles["close"] - candles["low"])
        / candles["range"].replace(0.0, np.nan)
    )
    # IMPORTANT: baseline uses only candles before the current candle.
    candles["prior_median_range_pips"] = (
        candles["range_pips"].rolling(30, min_periods=30).median().shift(1)
    )
    candles["range_ratio"] = (
        candles["range_pips"] / candles["prior_median_range_pips"]
    )
    return candles.dropna(subset=["range_ratio", "close_location"])


def generate_signal(
    ticks: pd.DataFrame,
    min_range_ratio: float = 2.0,
    edge_threshold: float = 0.70,
) -> ExtremeRejectionSignal:
    """Return a signal from the latest completed 3-minute candle."""
    candles = _candles(ticks)
    if len(candles) < 31:
        return ExtremeRejectionSignal("HOLD", 0.0, "insufficient completed 3-minute history")

    last = candles.iloc[-1]
    ratio = float(last["range_ratio"])
    location = float(last["close_location"])
    stamp = candles.index[-1].isoformat()

    if ratio < min_range_ratio:
        return ExtremeRejectionSignal(
            "HOLD", 0.0,
            f"range not extreme ({ratio:.2f}x prior 30-candle median)", stamp,
        )

    if location >= edge_threshold:
        # Candle expanded sharply and closed near its high -> rejection SELL.
        strength = min(0.90, 0.60 + 0.05 * min(ratio, 6.0))
        return ExtremeRejectionSignal(
            "SELL", strength,
            f"3m extreme rejection: range {ratio:.2f}x baseline; close at {location:.0%} of range",
            stamp,
        )

    if location <= 1.0 - edge_threshold:
        # Candle expanded sharply and closed near its low -> rejection BUY.
        strength = min(0.90, 0.60 + 0.05 * min(ratio, 6.0))
        return ExtremeRejectionSignal(
            "BUY", strength,
            f"3m extreme rejection: range {ratio:.2f}x baseline; close at {location:.0%} of range",
            stamp,
        )

    return ExtremeRejectionSignal(
        "HOLD", 0.0,
        f"extreme range but no edge rejection (close at {location:.0%})", stamp,
    )


def backtest_labels(
    ticks: pd.DataFrame,
    min_range_ratio: float = 2.0,
    edge_threshold: float = 0.70,
) -> pd.DataFrame:
    """Label every eligible completed candle with the next-candle direction."""
    candles = _candles(ticks).copy()
    candles["signal"] = "HOLD"
    sell = (
        (candles["range_ratio"] >= min_range_ratio)
        & (candles["close_location"] >= edge_threshold)
    )
    buy = (
        (candles["range_ratio"] >= min_range_ratio)
        & (candles["close_location"] <= 1.0 - edge_threshold)
    )
    candles.loc[sell, "signal"] = "SELL"
    candles.loc[buy, "signal"] = "BUY"

    candles["future_direction"] = np.sign(
        candles["close"].shift(-1) - candles["close"]
    )
    candles["correct"] = (
        ((candles["signal"] == "BUY") & (candles["future_direction"] > 0))
        | ((candles["signal"] == "SELL") & (candles["future_direction"] < 0))
    )
    return candles
