"""Binance public market-data adapter.

Only public candle data is handled here. No API key is required and this module
never creates orders.
"""
from __future__ import annotations

import pandas as pd

INTERVALS = {"1m", "5m", "15m"}


def normalize_klines(rows: list[list]) -> pd.DataFrame:
    columns = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]
    df = pd.DataFrame(rows, columns=columns[:len(rows[0])] if rows else columns)
    if df.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True, errors="coerce")
    return df[["timestamp", "open", "high", "low", "close"]].dropna().reset_index(drop=True)


def validate_interval(interval: str) -> str:
    if interval not in INTERVALS:
        raise ValueError(f"Supported intervals: {sorted(INTERVALS)}")
    return interval
