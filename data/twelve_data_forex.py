"""BiQuote real-time Forex 1-minute candle adapter.

BiQuote is used as the live Forex market-data source. No API key is required
for the public read endpoints. This adapter only reads market data; it does
not place trades.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pandas as pd

INTERVAL = "1min"
_INTERVAL_SECONDS = 60
_BASE_URL = "https://biquote.io"


def get_credit_usage() -> dict:
    """Return provider status in the shape expected by the existing dashboard."""
    return {
        "used": None,
        "left": None,
        "limit": None,
        "provider": "BiQuote",
        "free": True,
    }


def fetch_api_usage() -> dict:
    """Return a lightweight provider-health result without spending API credits."""
    req = Request(
        f"{_BASE_URL}/health",
        headers={"User-Agent": "mmc-signal-bot/1.0"},
    )
    try:
        with urlopen(req, timeout=8) as response:
            payload = json.load(response)
        return {"provider": "BiQuote", "free": True, "healthy": True, "details": payload}
    except Exception as exc:
        return {"provider": "BiQuote", "free": True, "healthy": False, "error": str(exc)}


def _closed_candles(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only candles whose full 1-minute interval has already closed in UTC."""
    if df.empty:
        return df
    now_utc = pd.Timestamp(datetime.now(timezone.utc))
    current_boundary = pd.Timestamp(
        (int(now_utc.timestamp()) // _INTERVAL_SECONDS) * _INTERVAL_SECONDS,
        unit="s",
        tz="UTC",
    )
    timestamps = pd.to_datetime(df["timestamp"], utc=True)
    return df.loc[timestamps < current_boundary].copy()


def fetch_forex_candles(symbol: str, interval: str = INTERVAL, outputsize: int = 200) -> pd.DataFrame:
    """Fetch closed 1-minute Forex OHLC candles from BiQuote."""
    if interval != INTERVAL:
        raise ValueError("Only the 1min interval is supported by the clean MMC strategy")
    if outputsize < 1:
        raise ValueError("outputsize must be at least 1")

    safe_symbol = quote(str(symbol).upper().strip(), safe="")
    params = urlencode({"interval": "1m", "limit": min(int(outputsize), 1000)})
    req = Request(
        f"{_BASE_URL}/api/{safe_symbol}/ohlc?{params}",
        headers={"User-Agent": "mmc-signal-bot/1.0", "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=10) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"BiQuote HTTP {exc.code} while fetching {symbol}") from exc
    except Exception as exc:
        raise RuntimeError(f"BiQuote connection error for {symbol}: {exc}") from exc

    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(str(payload.get("error")))

    values = payload.get("bars", []) if isinstance(payload, dict) else []
    if not isinstance(values, list) or not values:
        raise RuntimeError(f"BiQuote returned no candle data for {symbol}")

    df = pd.DataFrame(values)
    required = {"openTime", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"BiQuote candle response missing fields: {', '.join(sorted(missing))}")

    df["timestamp"] = pd.to_datetime(df["openTime"], unit="ms", utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[["timestamp", "open", "high", "low", "close"]].dropna().sort_values("timestamp")
    df = _closed_candles(df)
    if df.empty:
        raise RuntimeError(f"BiQuote returned no closed 1m candles for {symbol}")
    return df.tail(int(outputsize)).reset_index(drop=True)
