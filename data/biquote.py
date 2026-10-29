"""biquote Forex market-data ingestion.

Uses the public biquote REST API (no API key). Only completed, fresh 1-minute
OHLC candles are passed to the strategy; a fresh bid/ask quote is required.
"""
from __future__ import annotations

import re
import threading
import time

import pandas as pd
import requests

BASE_URL = "https://biquote.io/api"
_TIMEOUT_SECONDS = 12
_MAX_BARS = 1000
_SYMBOL_CACHE_TTL = 300
_SYMBOL_CACHE_LOCK = threading.Lock()
_SYMBOL_CACHE = {"items": [], "fetched_at": 0.0}
_DISCOVERED_SYMBOLS = {}


def _normalize_symbol_item(item):
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or item.get("symbol") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9._-]{2,24}", name) or "OTC" in name:
        return None
    return {"symbol": name, "name": str(item.get("description") or item.get("displayName") or name).strip(),
            "type": str(item.get("type") or item.get("assetClass") or "Other").strip(),
            "exchange": str(item.get("exchange") or "").strip(), "source": str(item.get("source") or "").strip()}


def fetch_biquote_symbols(query="", limit=100):
    """Discover real-market instruments from biquote's catalog/search API."""
    q = str(query or "").strip()
    cap = max(1, min(int(limit), 200))
    url = f"{BASE_URL}/symbols/search" if q else f"{BASE_URL}/active"
    params = {"q": q, "limit": cap} if q else {}
    if not q:
        now = time.time()
        with _SYMBOL_CACHE_LOCK:
            if _SYMBOL_CACHE["items"] and now - float(_SYMBOL_CACHE["fetched_at"]) < _SYMBOL_CACHE_TTL:
                return list(_SYMBOL_CACHE["items"])[:cap]
    try:
        response = requests.get(url, params=params, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError("biquote market catalog/search is temporarily unavailable.") from exc
    items = payload if isinstance(payload, list) else payload.get("items", payload.get("symbols", [])) if isinstance(payload, dict) else []
    cleaned, seen = [], set()
    for raw in items if isinstance(items, list) else []:
        item = _normalize_symbol_item(raw)
        if item and item["symbol"] not in seen:
            seen.add(item["symbol"])
            cleaned.append(item)
    with _SYMBOL_CACHE_LOCK:
        for item in cleaned:
            _DISCOVERED_SYMBOLS[item["symbol"]] = item
        if not q:
            _SYMBOL_CACHE.update(items=cleaned, fetched_at=time.time())
    return cleaned[:cap]


def known_biquote_symbols():
    with _SYMBOL_CACHE_LOCK:
        return sorted(set(_DISCOVERED_SYMBOLS))


def normalize_biquote_symbol(pair: str) -> str:
    """Normalize Forex, metal, crypto, index, or stock-CFD symbols."""
    raw = str(pair or "").strip().upper().replace("/", "").replace(" ", "")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{1,23}", raw) or "OTC" in raw:
        raise ValueError("Invalid biquote real-market symbol.")
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
