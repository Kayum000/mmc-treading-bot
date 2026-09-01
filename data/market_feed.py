"""Public live market feed helpers.

Uses Binance public REST klines for crypto. Forex is intentionally exposed as
an adapter boundary because a broker/data vendor should supply its authorized
live candles; this module never handles broker credentials or places orders.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.request import Request, urlopen
import json

import pandas as pd

BINANCE_INTERVALS = {"1m", "5m", "15m"}


@dataclass(frozen=True)
class MarketConfig:
    symbol: str = "BTCUSDT"
    limit: int = 200
    base_url: str = "https://api.binance.com/api/v3/klines"


def fetch_binance_klines(config: MarketConfig, interval: str) -> pd.DataFrame:
    if interval not in BINANCE_INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}")
    if not (50 <= config.limit <= 1000):
        raise ValueError("limit must be between 50 and 1000")
    url = f"{config.base_url}?symbol={config.symbol.upper()}&interval={interval}&limit={config.limit}"
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
    return {tf: fetch_binance_klines(config, tf) for tf in ("15m", "5m", "1m")}


def stream_crypto(config: MarketConfig, callback, poll_seconds: int = 5) -> None:
    """Poll public candles and invoke callback(frames) when a new 1m candle appears."""
    last_timestamp = None
    while True:
        frames = fetch_multi_timeframe(config)
        current = frames["1m"].iloc[-1]["timestamp"]
        if current != last_timestamp:
            callback(frames)
            last_timestamp = current
        time.sleep(max(1, poll_seconds))
