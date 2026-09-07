"""BiQuote real-time Forex candle adapter.

BiQuote is used as the live Forex market-data source. No API key is required
for the public read endpoints. This adapter only reads market data; it does
not place trades.
"""
from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pandas as pd

INTERVAL = "1min"
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


def _parse_open_time(values) -> pd.Series:
    """Parse BiQuote's documented ISO-8601 UTC timestamps, with numeric fallback."""
    parsed = pd.to_datetime(values, utc=True, errors="coerce")
    if parsed.notna().all():
        return parsed

    numeric = pd.to_numeric(values, errors="coerce")
    numeric_parsed = pd.to_datetime(numeric, unit="ms", utc=True, errors="coerce")
    return parsed.fillna(numeric_parsed)


def _closed_candles(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only completed candles; prefer BiQuote's explicit isOpen flag."""
    if df.empty:
        return df

    if "isOpen" in df.columns:
        is_open = df["isOpen"].astype("boolean")
        closed = df.loc[is_open.fillna(False).eq(False)].copy()
        if not closed.empty:
            return closed

    # Fallback for providers/older responses without isOpen.
    timestamps = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    current_boundary = pd.Timestamp.now(tz="UTC").floor("min")
    return df.loc[timestamps < current_boundary].copy()


def fetch_forex_candles(symbol: str, interval: str = INTERVAL, outputsize: int = 200) -> pd.DataFrame:
    """Fetch closed Forex OHLC candles from BiQuote while preserving the old engine contract."""
    interval_map = {
        "1min": "1m",
        "5min": "5m",
        "15min": "15m",
        "30min": "30m",
        "60min": "1h",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
    }
    biquote_interval = interval_map.get(str(interval).strip().lower())
    if not biquote_interval:
        raise ValueError(f"Unsupported Forex interval: {interval}")
    if outputsize < 1:
        raise ValueError("outputsize must be at least 1")

    safe_symbol = quote(str(symbol).replace("/", "").upper().strip(), safe="")
    params = urlencode({"interval": biquote_interval, "limit": min(int(outputsize), 1000)})
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

    df["timestamp"] = _parse_open_time(df["openTime"])
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    keep = ["timestamp", "open", "high", "low", "close"]
    df = df.dropna(subset=keep).sort_values("timestamp")
    df = _closed_candles(df)
    if df.empty:
        raise RuntimeError(f"BiQuote returned no closed {biquote_interval} candles for {symbol}")
    return df[keep].tail(int(outputsize)).reset_index(drop=True)
