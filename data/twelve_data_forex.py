"""Twelve Data real-time Forex candle adapter.

API keys are read from TWELVE_DATA_API_KEY and never stored in source control.
This adapter only reads market data; it does not place trades.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

INTERVALS = {"1min": "1m", "5min": "5m", "15min": "15m"}


def fetch_forex_candles(symbol: str, interval: str = "1min", outputsize: int = 200) -> pd.DataFrame:
    api_key = os.getenv("TWELVE_DATA_API_KEY")
    if not api_key:
        raise RuntimeError("Set TWELVE_DATA_API_KEY in the environment; never commit it to GitHub.")
    if interval not in INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}")
    params = urlencode({"symbol": symbol, "interval": interval, "outputsize": outputsize, "apikey": api_key})
    req = Request(f"https://api.twelvedata.com/time_series?{params}", headers={"User-Agent": "mmc-signal-bot/1.0"})
    with urlopen(req, timeout=10) as response:
        payload = json.load(response)
    if payload.get("status") == "error":
        raise RuntimeError(payload.get("message", "Twelve Data API error"))
    values = payload.get("values", [])
    df = pd.DataFrame(values)
    if df.empty:
        raise RuntimeError("Twelve Data returned no candle data")
    df["timestamp"] = pd.to_datetime(df["datetime"], utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["timestamp", "open", "high", "low", "close"]].dropna().sort_values("timestamp")


def fetch_forex_multi_timeframe(symbol: str) -> dict[str, pd.DataFrame]:
    """Fetch 1m/5m/15m candles concurrently for the selected pair.

    The strategy still receives exactly the same three DataFrames; only the
    network wait is parallelized so one slow timeframe does not block the
    other two from being fetched.
    """
    intervals = list(INTERVALS.items())
    with ThreadPoolExecutor(max_workers=len(intervals)) as executor:
        futures = {
            label: executor.submit(fetch_forex_candles, symbol, interval)
            for interval, label in intervals
        }
        return {label: futures[label].result() for _, label in intervals}
