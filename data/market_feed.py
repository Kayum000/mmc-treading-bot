"""Public 1-minute market feed helpers for the canonical MMC strategy.

Uses Binance public REST klines for crypto.  This module intentionally exposes
only completed 1-minute candles and never performs multi-timeframe analysis.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.request import Request, urlopen

import pandas as pd

INTERVAL = "1m"


@dataclass(frozen=True)
class MarketConfig:
    symbol: str = "BTCUSDT"
    limit: int = 200
    base_url: str = "https://api.binance.com/api/v3/klines"


def fetch_binance_klines(config: MarketConfig, interval: str = INTERVAL) -> pd.DataFrame:
    if interval != INTERVAL:
        raise ValueError("Only the 1m interval is supported by the MMC feed")
    if not (50 <= config.limit <= 1000):
        raise ValueError("limit must be between 50 and 1000")
    url = f"{config.base_url}?symbol={config.symbol.upper()}&interval=1m&limit={config.limit}"
    req = Request(url, headers={"User-Agent": "mmc-signal-bot/1.0"})
    with urlopen(req, timeout=10) as response:
        rows = json.load(response)
    columns = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "buy_volume", "buy_quote_volume", "ignore"]
    df = pd.DataFrame(rows, columns=columns)
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["timestamp", "open", "high", "low", "close"]].dropna()


def fetch_multi_timeframe(config: MarketConfig) -> dict[str, pd.DataFrame]:
    """Return a single-key frame map for backwards compatibility; never MTF."""
    return {INTERVAL: fetch_binance_klines(config, INTERVAL)}


def stream_crypto(config: MarketConfig, callback, poll_seconds: int = 5) -> None:
    """Poll public 1m candles and invoke callback(frames) when a new candle appears."""
    last_timestamp = None
    while True:
        frames = fetch_multi_timeframe(config)
        current = frames[INTERVAL].iloc[-1]["timestamp"]
        if current != last_timestamp:
            callback(frames)
            last_timestamp = current
        time.sleep(max(1, poll_seconds))
