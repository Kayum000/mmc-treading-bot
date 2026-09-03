"""Binance spot crypto candle adapter for MMC signals."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

INTERVALS = {"30m": "30m", "15m": "15m", "5m": "5m"}
_INTERVAL_SECONDS = {"30m": 1800, "15m": 900, "5m": 300}
BINANCE_BASE_URLS = (
    "https://data-api.binance.vision",
    "https://api-gcp.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
    "https://api.binance.com",
)


def _fetch_payload(symbol: str, interval: str, limit: int) -> list:
    params = urlencode({"symbol": symbol.upper(), "interval": interval, "limit": limit})
    last_error = None

    for base_url in BINANCE_BASE_URLS:
        req = Request(
            f"{base_url}/api/v3/klines?{params}",
            headers={"User-Agent": "mmc-signal-bot/1.0", "Accept": "application/json"},
        )
        try:
            with urlopen(req, timeout=10) as response:
                payload = json.load(response)
            if isinstance(payload, dict) and payload.get("code"):
                last_error = RuntimeError(payload.get("msg", "Binance API error"))
                continue
            if not payload:
                last_error = RuntimeError("Binance returned no candle data")
                continue
            return payload
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            continue

    raise RuntimeError(f"Binance market data unavailable: {last_error}")


def _closed_candles(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Keep only candles whose full interval has already closed in UTC."""
    if df.empty:
        return df
    cutoff = pd.Timestamp(datetime.now(timezone.utc)) - pd.Timedelta(seconds=_INTERVAL_SECONDS[interval])
    return df.loc[df["timestamp"] <= cutoff].copy()


def fetch_crypto_candles(symbol: str, interval: str = "5m", limit: int = 200) -> pd.DataFrame:
    if interval not in INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}")

    payload = _fetch_payload(symbol, interval, limit)
    columns = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(payload, columns=columns)
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[["timestamp", "open", "high", "low", "close"]].dropna().sort_values("timestamp")
    df = _closed_candles(df, interval)
    if df.empty:
        raise RuntimeError(f"Binance returned no closed {interval} candles")
    return df.reset_index(drop=True)


def fetch_crypto_multi_timeframe(symbol: str) -> dict[str, pd.DataFrame]:
    """Fetch closed 30m/15m/5m candles for the selected crypto pair."""
    return {label: fetch_crypto_candles(symbol, interval) for interval, label in INTERVALS.items()}
