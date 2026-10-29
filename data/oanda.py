"""OANDA v20 market-data ingestion for MMC Trading Bot."""
from __future__ import annotations

import os
import re
import time

import pandas as pd
import requests

_TIMEOUT_SECONDS = 12


def _credentials() -> tuple[str, str, str]:
    token = os.getenv("OANDA_ACCESS_TOKEN", "").strip()
    account = os.getenv("OANDA_ACCOUNT_ID", "").strip()
    environment = os.getenv("OANDA_ENVIRONMENT", "practice").strip().lower()
    if not token:
        raise RuntimeError("OANDA_ACCESS_TOKEN is not configured on the server.")
    if not account:
        raise RuntimeError("OANDA_ACCOUNT_ID is not configured on the server.")
    if environment not in {"practice", "live"}:
        raise RuntimeError("OANDA_ENVIRONMENT must be 'practice' or 'live'.")
    host = "https://api-fxpractice.oanda.com" if environment == "practice" else "https://api-fxtrade.oanda.com"
    return token, account, host


def normalize_oanda_instrument(pair: str) -> str:
    raw = str(pair or "").strip().upper().replace("/", "_").replace("-", "_")
    if "_" not in raw and len(raw) == 6:
        raw = f"{raw[:3]}_{raw[3:]}"
    if not re.fullmatch(r"[A-Z]{3}_[A-Z]{3}", raw):
        raise ValueError("OANDA Forex mode expects a currency pair such as EUR_USD or EURUSD.")
    return raw


def _get(url: str, params: dict) -> dict:
    token, _, _ = _credentials()
    try:
        response = requests.get(
            url, params=params, timeout=_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {token}", "Accept-Datetime-Format": "RFC3339"},
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 403):
            raise RuntimeError("OANDA rejected the token or account access.") from exc
        if status == 429:
            raise RuntimeError("OANDA rate limit reached; wait before retrying.") from exc
        raise RuntimeError("OANDA market-data request failed; check network and API status.") from exc
    except ValueError as exc:
        raise RuntimeError("OANDA returned an unreadable response.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("OANDA returned an invalid response.")
    return payload


def fetch_oanda_candles(pair: str, count: int = 1200) -> pd.DataFrame:
    """Return validated completed 1-minute midpoint OHLC candles."""
    token, account, host = _credentials()
    instrument = normalize_oanda_instrument(pair)
    # _get reads the same token from environment; token is intentionally never logged.
    payload = _get(
        f"{host}/v3/accounts/{account}/instruments/{instrument}/candles",
        {"granularity": "M1", "price": "M", "count": max(60, min(int(count), 5000)), "smooth": "false"},
    )
    rows = []
    for candle in payload.get("candles", []):
        if not isinstance(candle, dict) or not candle.get("complete"):
            continue
        mid = candle.get("mid") or {}
        try:
            rows.append({
                "timestamp": pd.to_datetime(candle["time"], utc=True, errors="raise"),
                "open": float(mid["o"]), "high": float(mid["h"]),
                "low": float(mid["l"]), "close": float(mid["c"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    frame = pd.DataFrame(rows)
    required = ["timestamp", "open", "high", "low", "close"]
    if frame.empty:
        raise RuntimeError("OANDA returned no completed M1 candles for this instrument.")
    frame = frame.dropna(subset=required).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    now = pd.Timestamp.now(tz="UTC")
    frame = frame.loc[frame["timestamp"] < now.floor("min")].reset_index(drop=True)
    if len(frame) < 60:
        raise RuntimeError("OANDA returned fewer than 60 completed M1 candles.")
    if (now - frame.iloc[-1]["timestamp"]).total_seconds() > 300:
        raise RuntimeError("OANDA latest completed M1 candle is stale (over 5 minutes old).")
    values = frame[["open", "high", "low", "close"]]
    if (values <= 0).any().any():
        raise RuntimeError("OANDA returned invalid non-positive Forex prices.")
    if ((frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any()
            or (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any()):
        raise RuntimeError("OANDA returned inconsistent OHLC values.")
    frame["source"] = "OANDA"
    return frame


def fetch_oanda_quote(pair: str) -> dict:
    """Fetch current bid/ask and midpoint for a single instrument."""
    _, account, host = _credentials()
    instrument = normalize_oanda_instrument(pair)
    payload = _get(
        f"{host}/v3/accounts/{account}/pricing",
        {"instruments": instrument},
    )
    prices = payload.get("prices") or []
    if not prices:
        raise RuntimeError(f"OANDA returned no current quote for {instrument}.")
    price = prices[0]
    try:
        bids = [float(x["price"]) for x in price.get("bids", []) if float(x.get("liquidity", 0)) > 0]
        asks = [float(x["price"]) for x in price.get("asks", []) if float(x.get("liquidity", 0)) > 0]
        bid = max(bids) if bids else float(price["closeoutBid"])
        ask = min(asks) if asks else float(price["closeoutAsk"])
        timestamp = pd.to_datetime(price["time"], utc=True, errors="raise")
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("OANDA returned an invalid quote payload.") from exc
    age = (pd.Timestamp.now(tz="UTC") - timestamp).total_seconds()
    if age > 60 or age < -5:
        raise RuntimeError("OANDA latest quote is stale or has an invalid timestamp.")
    return {
        "instrument": instrument, "bid": bid, "ask": ask,
        "price": (bid + ask) / 2, "timestamp": int(timestamp.timestamp()),
        "age_seconds": round(max(0, age), 2),
    }
