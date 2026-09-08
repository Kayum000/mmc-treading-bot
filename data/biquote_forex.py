"""Free real-time Forex adapter backed by BiQuote public market data."""
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
    if df.empty:
        return df
    now_utc = pd.Timestamp(datetime.now(timezone.utc))
    boundary = pd.Timestamp((int(now_utc.timestamp()) // 60) * 60, unit="s", tz="UTC")
    timestamps = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df.loc[timestamps < boundary].copy()


def fetch_forex_candles(symbol: str, interval: str = INTERVAL, outputsize: int = 200) -> pd.DataFrame:
    if interval != INTERVAL:
        raise ValueError("Only the 1min interval is supported by the selected strategy")
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
                "open": float(bar["open"]), "high": float(bar["high"]),
                "low": float(bar["low"]), "close": float(bar["close"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"BiQuote returned invalid candle data for {clean_symbol}")
    df = df[["timestamp", "open", "high", "low", "close"]].dropna().sort_values("timestamp")
    df = _closed_candles(df)
    if df.empty:
        raise RuntimeError(f"BiQuote returned no closed 1m candles for {clean_symbol}")
    return df.reset_index(drop=True)


def fetch_latest_tick(symbol: str) -> dict:
    clean_symbol = symbol.replace("/", "").upper()
    payload = _request_json(f"{BASE_URL}/api/{quote(clean_symbol)}")
    if not isinstance(payload, dict):
        raise RuntimeError("BiQuote returned an invalid tick response")
    return payload


def fetch_tick_history(symbol: str, count: int = 1000) -> pd.DataFrame:
    """Return newest BiQuote ticks, preserving volume fields when present."""
    clean_symbol = symbol.replace("/", "").upper()
    limit = max(1, min(int(count), 1000))
    payload = _request_json(f"{BASE_URL}/api/{quote(clean_symbol)}/history?count={limit}")
    rows = payload.get("ticks", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"BiQuote returned no tick history for {clean_symbol}")
    out = []
    for tick in rows:
        if not isinstance(tick, dict):
            continue
        try:
            row = {
                "timestamp": pd.to_datetime(tick.get("timestamp"), utc=True),
                "askPrice": float(tick["ask"]),
                "bidPrice": float(tick["bid"]),
            }
            if tick.get("askVolume") is not None and tick.get("bidVolume") is not None:
                row["askVolume"] = float(tick["askVolume"])
                row["bidVolume"] = float(tick["bidVolume"])
            out.append(row)
        except (KeyError, TypeError, ValueError):
            continue
    df = pd.DataFrame(out).dropna(subset=["timestamp", "askPrice", "bidPrice"])
    df = df.sort_values("timestamp").drop_duplicates("timestamp")
    if df.empty:
        raise RuntimeError(f"BiQuote returned invalid tick history for {clean_symbol}")
    return df.reset_index(drop=True)


def get_credit_usage() -> dict:
    return {"used": None, "left": None, "limit": None}


def fetch_api_usage() -> dict:
    return {"provider": "BiQuote", "api_key_required": False, "credits": "unmetered_public_feed"}
