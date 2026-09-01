"""Quotex data adapter boundary.

This module intentionally does not automate login, scrape credentials, or place
orders. Quotex does not provide a public trading API that this project can rely
on. Feed normalized OHLC candles into `append_candle` from an authorized data
source or a user-maintained connector.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import pandas as pd

REQUIRED = ("timestamp", "open", "high", "low", "close")


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


def normalize_candles(rows: Iterable[Candle]) -> pd.DataFrame:
    df = pd.DataFrame([r.__dict__ for r in rows])
    if df.empty:
        return pd.DataFrame(columns=REQUIRED)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Missing candle fields: {missing}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for col in REQUIRED[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=REQUIRED).sort_values("timestamp").drop_duplicates("timestamp")


def append_candle(buffer: pd.DataFrame, candle: Candle) -> pd.DataFrame:
    incoming = normalize_candles([candle])
    if buffer.empty:
        return incoming
    return normalize_candles([
        Candle(row.timestamp.to_pydatetime(), row.open, row.high, row.low, row.close)
        for row in pd.concat([buffer, incoming], ignore_index=True).itertuples(index=False)
    ])
