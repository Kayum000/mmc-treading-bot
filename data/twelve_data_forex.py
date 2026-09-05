"""Twelve Data real-time Forex candle adapter.

API keys are read from TWELVE_DATA_API_KEY and never stored in source control.
This adapter only reads market data; it does not place trades.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

INTERVALS = {"30min": "30m", "15min": "15m", "5min": "5m", "1min": "1m"}
_INTERVAL_SECONDS = {"30min": 1800, "15min": 900, "5min": 300, "1min": 60}

_LAST_CREDIT_USAGE = {"used": None, "left": None, "limit": None}


def _record_credit_headers(headers) -> None:
    used = headers.get("api-credits-used")
    left = headers.get("api-credits-left")
    if used is not None or left is not None:
        try:
            used_i = int(used) if used is not None else None
            left_i = int(left) if left is not None else None
            limit_i = (used_i + left_i) if used_i is not None and left_i is not None else None
            _LAST_CREDIT_USAGE.update({"used": used_i, "left": left_i, "limit": limit_i})
        except ValueError:
            pass


def get_credit_usage() -> dict:
    return dict(_LAST_CREDIT_USAGE)


def fetch_api_usage() -> dict:
    """Fetch real account usage; this endpoint costs 1 API credit."""
    api_key = os.getenv("TWELVE_DATA_API_KEY")
    if not api_key:
        raise RuntimeError("Set TWELVE_DATA_API_KEY in the environment; never commit it to GitHub.")
    params = urlencode({"apikey": api_key})
    req = Request(
        f"https://api.twelvedata.com/api_usage?{params}",
        headers={"User-Agent": "mmc-signal-bot/1.0"},
    )
    with urlopen(req, timeout=10) as response:
        _record_credit_headers(response.headers)
        return json.load(response)


def _closed_candles(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Keep only candles whose full interval has already closed in UTC.

    Twelve Data timestamps represent candle start times. A candle is complete
    once its next interval boundary has passed. Using the current interval
    boundary avoids the old ``now - interval`` ambiguity around minute edges.
    """
    if df.empty:
        return df
    now_utc = pd.Timestamp(datetime.now(timezone.utc))
    seconds = _INTERVAL_SECONDS[interval]
    current_boundary = pd.Timestamp((int(now_utc.timestamp()) // seconds) * seconds, unit="s", tz="UTC")
    timestamps = pd.to_datetime(df["timestamp"], utc=True)
    return df.loc[timestamps < current_boundary].copy()


def fetch_forex_candles(symbol: str, interval: str = "5min", outputsize: int = 200) -> pd.DataFrame:
    api_key = os.getenv("TWELVE_DATA_API_KEY")
    if not api_key:
        raise RuntimeError("Set TWELVE_DATA_API_KEY in the environment; never commit it to GitHub.")
    if interval not in INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}")

    params = urlencode({
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "timezone": "UTC",
        "apikey": api_key,
    })
    req = Request(
        f"https://api.twelvedata.com/time_series?{params}",
        headers={"User-Agent": "mmc-signal-bot/1.0"},
    )
    try:
        with urlopen(req, timeout=10) as response:
            _record_credit_headers(response.headers)
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError(
                "Twelve Data rate limit reached (HTTP 429). Wait for the next API-credit minute and try again."
            ) from exc
        raise

    if payload.get("status") == "error":
        raise RuntimeError(payload.get("message", "Twelve Data API error"))
    values = payload.get("values", [])
    df = pd.DataFrame(values)
    if df.empty:
        raise RuntimeError("Twelve Data returned no candle data")
    df["timestamp"] = pd.to_datetime(df["datetime"], utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[["timestamp", "open", "high", "low", "close"]].dropna().sort_values("timestamp")
    df = _closed_candles(df, interval)
    if df.empty:
        raise RuntimeError(f"Twelve Data returned no closed {INTERVALS[interval]} candles")
    return df.reset_index(drop=True)


def fetch_forex_multi_timeframe(symbol: str) -> dict[str, pd.DataFrame]:
    """Fetch closed 30m/15m/5m candles for the selected pair sequentially."""
    return {
        label: fetch_forex_candles(symbol, interval)
        for interval, label in INTERVALS.items()
        if label in {"30m", "15m", "5m"}
    }
