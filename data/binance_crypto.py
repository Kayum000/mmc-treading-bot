"""Public Binance Spot market-data adapter for Quotex-labelled crypto pairs.

Dashboard labels intentionally match Quotex (for example BTC/USD), while the
underlying public Binance Spot symbols use USDT quote markets (for example BTCUSDT).
This adapter is read-only and does not place orders.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import requests

BASE_URL = "https://data-api.binance.vision/api/v3"
CRYPTO_MARKET_MAP = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "LTC/USD": "LTCUSDT",
    "XRP/USD": "XRPUSDT",
    "BCH/USD": "BCHUSDT",
    "ADA/USD": "ADAUSDT",
    "DOT/USD": "DOTUSDT",
    "LINK/USD": "LINKUSDT",
    "UNI/USD": "UNIUSDT",
    "SOL/USD": "SOLUSDT",
    "AVAX/USD": "AVAXUSDT",
    "DOGE/USD": "DOGEUSDT",
    "SHIB/USD": "SHIBUSDT",
}
CRYPTO_DISPLAY_PAIRS = tuple(CRYPTO_MARKET_MAP.keys())
_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}


def binance_symbol_for_pair(pair: str) -> str:
    label = str(pair or "").strip().upper()
    symbol = CRYPTO_MARKET_MAP.get(label)
    if not symbol:
        raise ValueError(f"Unsupported crypto market: {pair}")
    return symbol


def fetch_crypto_candles(pair: str, interval: str = "1m", limit: int = 200) -> pd.DataFrame:
    """Fetch only fully closed Binance Spot candles, normalized for MMC strategies."""
    symbol = binance_symbol_for_pair(pair)
    if interval == "1D":
        interval = "1d"
    if interval not in _INTERVALS:
        raise ValueError(f"Unsupported Binance candle interval: {interval}")
    count = max(60, min(int(limit), 1000))
    response = requests.get(
        f"{BASE_URL}/klines",
        params={"symbol": symbol, "interval": interval, "limit": count},
        headers={"User-Agent": "MMC-Trading-Bot/1.0"},
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"Binance returned no candle data for {symbol}")
    rows = []
    for candle in payload:
        try:
            rows.append({
                "timestamp": pd.to_datetime(int(candle[0]), unit="ms", utc=True),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
                "close_time_ms": int(candle[6]),
            })
        except (IndexError, TypeError, ValueError):
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"Binance returned invalid candles for {symbol}")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    df = df[df["close_time_ms"] < now_ms].copy()
    if df.empty:
        raise RuntimeError(f"Binance returned no closed {interval} candles for {symbol}")
    return df[["timestamp", "open", "high", "low", "close", "volume"]].dropna().sort_values("timestamp").reset_index(drop=True)
