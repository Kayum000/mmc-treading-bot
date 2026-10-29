"""biquote Forex market-data ingestion.

Uses the public biquote REST API (no API key). Only completed, fresh 1-minute
OHLC candles are passed to the strategy; a fresh bid/ask quote is required.
"""
from __future__ import annotations

import re

import pandas as pd
import requests

BASE_URL = "https://biquote.io/api"
_TIMEOUT_SECONDS = 12
_MAX_BARS = 1000


def normalize_biquote_symbol(pair: str) -> str:
    """Normalize EURUSD, EUR/USD, or EUR-USD to biquote's EURUSD ticker."""
    raw = str(pair or "").strip().upper().replace("/", "").replace("_", "").replace("-", "")
    if not re.fullmatch(r"[A-Z]{6}", raw):
        raise ValueError("biquote Real Forex mode expects a pair such as EURUSD or EUR/USD.")
    return raw


def fetch_biquote_candles(pair: str, count: int = 1200) -> pd.DataFrame:
    """Fetch and validate completed M1 candles; never synthesize missing bars."""
    symbol = normalize_biquote_symbol(pair)
    limit = max(60, min(int(count), _MAX_BARS))
    try:
        response = requests.get(f"{BASE_URL}/{symbol}/ohlc",
                                params={"interval": "1m", "limit": limit}, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError("biquote candle request failed; check provider availability and network.") from exc
    except ValueError as exc:
        raise RuntimeError("biquote returned an unreadable candle response.") from exc
    bars = payload.get("bars") if isinstance(payload, dict) else None
    if not isinstance(bars, list) or not bars:
        raise RuntimeError(f"biquote returned no M1 candles for {symbol}.")
    rows = []
    for bar in bars:
        if not isinstance(bar, dict) or bar.get("isOpen") is True:
            continue
        try:
            stamp = pd.to_datetime(bar.get("openTime"), utc=True, errors="coerce")
            row = {"timestamp": stamp, "open": float(bar["open"]), "high": float(bar["high"]),
                   "low": float(bar["low"]), "close": float(bar["close"])}
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if pd.isna(stamp):
            continue
        rows.append(row)
    frame = pd.DataFrame(rows)
    required = ["timestamp", "open", "high", "low", "close"]
    if frame.empty:
        raise RuntimeError(f"biquote returned no completed M1 candles for {symbol}.")
    frame = frame.dropna(subset=required).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    now = pd.Timestamp.now(tz="UTC")
    frame = frame.loc[frame["timestamp"] < now.floor("min")].reset_index(drop=True)
    if frame.empty:
        raise RuntimeError(f"biquote has no completed 1-minute candles for {symbol}.")
    latest_open = frame.iloc[-1]["timestamp"]
    if (now - latest_open).total_seconds() > 300:
        raise RuntimeError("biquote latest completed M1 candle is stale (over 5 minutes old).")
    values = frame[["open", "high", "low", "close"]]
    if (values <= 0).any().any():
        raise RuntimeError("biquote returned invalid non-positive Forex prices.")
    if ((frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any()
            or (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any()):
        raise RuntimeError("biquote returned inconsistent OHLC values.")
    frame["source"] = "biquote"
    return frame.tail(limit).reset_index(drop=True)


def fetch_biquote_quote(pair: str) -> dict:
    """Fetch a fresh bid/ask midpoint quote and validate its timestamp."""
    symbol = normalize_biquote_symbol(pair)
    try:
        response = requests.get(f"{BASE_URL}/{symbol}", params={"allowStale": "false"}, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError("biquote live quote request failed; check provider availability and market hours.") from exc
    except ValueError as exc:
        raise RuntimeError("biquote returned an unreadable quote response.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("biquote returned an invalid quote response.")
    try:
        bid, ask = float(payload["bid"]), float(payload["ask"])
        mid = float(payload.get("mid", (bid + ask) / 2))
        stamp = pd.to_datetime(payload["timestamp"], utc=True, errors="raise")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError(f"biquote returned an invalid quote for {symbol}.") from exc
    if any(not (value > 0 and value < float("inf")) for value in (bid, ask, mid)) or ask < bid:
        raise RuntimeError("biquote returned invalid bid/ask prices.")
    age = (pd.Timestamp.now(tz="UTC") - stamp).total_seconds()
    if age < -5 or age > 60 or payload.get("stale") is True or payload.get("marketState") == "closed":
        raise RuntimeError("biquote quote is stale or the Forex market is closed.")
    return {"symbol": symbol, "bid": bid, "ask": ask, "price": mid,
            "timestamp": int(stamp.timestamp()), "age_seconds": round(max(0.0, age), 2), "source": "biquote"}
