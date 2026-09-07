"""Free real-time Forex adapter backed by BiQuote public market data.

BiQuote exposes public REST endpoints without an API key. This module keeps
market-data handling isolated so the existing MMC engine can use the feed
without changing strategy logic.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

BASE_URL = "https://biquote.io"
INTERVAL = "1min"


def _request_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "mmc-signal-bot/1.0"})
    try:
        with urlopen(req, timeout=12) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"BiQuote HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"BiQuote connection error: {exc.reason}") from exc


def _closed_candles(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only fully closed 1-minute candles in UTC."""
    if df.empty:
        return df
    now_utc = pd.Timestamp(datetime.now(timezone.utc))
    boundary = pd.Timestamp(
        (int(now_utc.timestamp()) // 60) * 60,
        unit="s",
        tz="UTC",
    )
    timestamps = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df.loc[timestamps < boundary].copy()


def fetch_forex_candles(symbol: str, interval: str = INTERVAL, outputsize: int = 200) -> pd.DataFrame:
    """Return closed 1-minute OHLC candles in the legacy engine format."""
    if interval != INTERVAL:
        raise ValueError("Only the 1min interval is supported by the clean MMC strategy")

    clean_symbol = symbol.replace("/", "").upper()
    limit = max(1, min(int(outputsize), 1000))
    url = f"{BASE_URL}/api/{quote(clean_symbol)}/ohlc?interval=1m&limit={limit}"
    payload = _request_json(url)
    bars = payload.get("bars", []) if isinstance(payload, dict) else []
    if not bars:
        raise RuntimeError(f"BiQuote returned no candle data for {clean_symbol}")

    rows = []
    for bar in bars:
        try:
            rows.append({
                "timestamp": pd.to_datetime(bar["openTime"], utc=True),
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
            })
        except (KeyError, TypeError, ValueError):
            continue

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"BiQuote returned invalid candle data for {clean_symbol}")

    df = df[["timestamp", "open", "high", "low", "close"]].dropna()
    df = df.sort_values("timestamp")
    df = _closed_candles(df)
    if df.empty:
        raise RuntimeError(f"BiQuote returned no closed 1m candles for {clean_symbol}")
    return df.reset_index(drop=True)


def fetch_latest_tick(symbol: str) -> dict:
    """Return the latest public tick, including market freshness metadata."""
    clean_symbol = symbol.replace("/", "").upper()
    payload = _request_json(f"{BASE_URL}/api/{quote(clean_symbol)}")
    if not isinstance(payload, dict):
        raise RuntimeError("BiQuote returned an invalid tick response")
    return payload


def get_credit_usage() -> dict:
    """Compatibility response: this feed has no account credit meter."""
    return {"used": None, "left": None, "limit": None}


def fetch_api_usage() -> dict:
    """Compatibility response for the existing dashboard usage widget."""
    return {"provider": "BiQuote", "api_key_required": False, "credits": "unmetered_public_feed"}
