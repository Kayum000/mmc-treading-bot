"""Binance spot crypto candle adapter for on-demand MMC signals."""
from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m"}
BINANCE_URL = "https://api.binance.com/api/v3/klines"


def fetch_crypto_candles(symbol: str, interval: str = "1m", limit: int = 200) -> pd.DataFrame:
    if interval not in INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}")
    params = urlencode({"symbol": symbol.upper(), "interval": interval, "limit": limit})
    req = Request(f"{BINANCE_URL}?{params}", headers={"User-Agent": "mmc-signal-bot/1.0"})
    with urlopen(req, timeout=10) as response:
        payload = json.load(response)
    if isinstance(payload, dict) and payload.get("code"):
        raise RuntimeError(payload.get("msg", "Binance API error"))
    if not payload:
        raise RuntimeError("Binance returned no candle data")

    columns = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(payload, columns=columns)
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["timestamp", "open", "high", "low", "close"]].dropna().sort_values("timestamp")


def fetch_crypto_multi_timeframe(symbol: str) -> dict[str, pd.DataFrame]:
    """Fetch 1m/5m/15m candles concurrently for the selected crypto pair."""
    from concurrent.futures import ThreadPoolExecutor

    intervals = list(INTERVALS)
    with ThreadPoolExecutor(max_workers=len(intervals)) as executor:
        futures = {label: executor.submit(fetch_crypto_candles, symbol, label) for label in intervals}
        return {label: futures[label].result() for label in intervals}
