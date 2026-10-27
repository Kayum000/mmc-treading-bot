"""Twelve Data Forex candle ingestion.

API keys are read only from the server environment and never logged or returned.
"""
from __future__ import annotations

import os
import re

import pandas as pd
import requests

BASE_URL = "https://api.twelvedata.com/time_series"
_TIMEOUT_SECONDS = 12


def normalize_forex_symbol(pair: str) -> str:
    """Normalize EURUSD/EUR/USD to Twelve Data's EUR/USD form."""
    raw = str(pair or "").strip().upper().replace("_", "/").replace("-", "/")
    if "/" not in raw and len(raw) == 6:
        raw = f"{raw[:3]}/{raw[3:]}"
    if not re.fullmatch(r"[A-Z]{3}/[A-Z]{3}", raw):
        raise ValueError("Real Forex mode expects a currency pair such as EUR/USD or EURUSD.")
    return raw


def fetch_twelve_data_candles(pair: str, count: int = 1200) -> pd.DataFrame:
    """Fetch and validate 1-minute Forex OHLC candles; never synthesize missing bars."""
    api_key = os.getenv("TWELVEDATA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TWELVEDATA_API_KEY is not configured on the server.")

    symbol = normalize_forex_symbol(pair)
    params = {
        "symbol": symbol,
        "interval": "1min",
        "outputsize": max(60, min(int(count), 5000)),
        "order": "asc",
        "timezone": "UTC",
        "include_ohlc": "true",
        "apikey": api_key,
    }
    try:
        response = requests.get(BASE_URL, params=params, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError("Twelve Data request failed; check network and provider status.") from exc
    except ValueError as exc:
        raise RuntimeError("Twelve Data returned an unreadable response.") from exc

    if payload.get("status") == "error" or not isinstance(payload.get("values"), list):
        message = str(payload.get("message") or "No candle data returned")
        code = payload.get("code")
        # Do not echo the request URL because it can contain the API key.
        if code in (401, 403) or "apikey" in message.lower() or "api key" in message.lower():
            raise RuntimeError("Twelve Data rejected the API key or the plan does not permit this endpoint.")
        if code == 429 or "limit" in message.lower():
            raise RuntimeError("Twelve Data request limit reached; wait for the quota to reset.")
        raise RuntimeError(f"Twelve Data candle data unavailable for {symbol}: {message[:180]}")

    frame = pd.DataFrame(payload["values"])
    required = {"datetime", "open", "high", "low", "close"}
    if frame.empty or not required.issubset(frame.columns):
        raise RuntimeError("Twelve Data did not return the required OHLC candle fields.")

    frame = frame.rename(columns={"datetime": "timestamp"})
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)

    # Twelve Data timestamps candles by their opening time. Exclude the currently
    # forming minute so the strategy only sees completed candles.
    now = pd.Timestamp.now(tz="UTC")
    current_minute = now.floor("min")
    frame = frame.loc[frame["timestamp"] < current_minute].copy().reset_index(drop=True)
    if frame.empty:
        raise RuntimeError("Twelve Data has no completed 1-minute candles for this pair.")
    latest_open = frame.iloc[-1]["timestamp"]
    age_seconds = (now - latest_open).total_seconds()
    if age_seconds > 300:
        raise RuntimeError("Twelve Data's latest completed candle is stale (over 5 minutes old).")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise RuntimeError("Twelve Data returned invalid non-positive Forex prices.")
    if (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any()
        or (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any()
    ):
        raise RuntimeError("Twelve Data returned inconsistent OHLC values.")

    frame["source"] = "Twelve Data"
    return frame
