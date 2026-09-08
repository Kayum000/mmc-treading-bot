"""Public current 1-minute crypto candle helper for running entry analysis."""
from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

BASES = ("https://data-api.binance.vision", "https://api.binance.com", "https://api-gcp.binance.com")


def _get(url: str):
    req = Request(url, headers={"User-Agent": "mmc-signal-bot/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=8) as response:
        return json.load(response)


def fetch_crypto_running_candle(symbol: str) -> pd.DataFrame:
    symbol = symbol.strip().upper().replace("/", "")
    last = None
    for base in BASES:
        try:
            q = urlencode({"symbol": symbol, "interval": "1m", "limit": 200})
            rows = _get(f"{base}/api/v3/klines?{q}")
            if not isinstance(rows, list) or not rows:
                raise RuntimeError("no Binance klines")
            cols = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "tb_base", "tb_quote", "ignore"]
            df = pd.DataFrame(rows, columns=cols)
            df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            for col in ("open", "high", "low", "close"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df[["timestamp", "open", "high", "low", "close"]].dropna().sort_values("timestamp")
            return df.reset_index(drop=True)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"Running crypto candle unavailable: {last}")
