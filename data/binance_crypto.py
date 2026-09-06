"""Crypto candle adapter for the clean single-timeframe MMC strategy."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

INTERVAL = "1m"
_INTERVAL_SECONDS = 60
BINANCE_BASE_URLS = (
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
)
BYBIT_BASE_URL = "https://api.bybit.com"


def _http_json(url: str) -> object:
    req = Request(url, headers={"User-Agent": "mmc-signal-bot/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def _fetch_binance_payload(symbol: str, limit: int, start_ms: int | None = None, end_ms: int | None = None) -> list:
    params_dict = {"symbol": symbol.upper(), "interval": INTERVAL, "limit": min(limit, 1000)}
    if start_ms is not None:
        params_dict["startTime"] = start_ms
    if end_ms is not None:
        params_dict["endTime"] = end_ms
    params = urlencode(params_dict)
    last_error = None
    for base_url in BINANCE_BASE_URLS:
        try:
            payload = _http_json(f"{base_url}/api/v3/klines?{params}")
            if isinstance(payload, dict) and payload.get("code"):
                last_error = RuntimeError(str(payload.get("msg", "Binance API error")))
                continue
            if isinstance(payload, list) and payload:
                return payload
            last_error = RuntimeError("Binance returned no candle data")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            continue
    raise RuntimeError(f"Binance market data unavailable: {last_error}")


def _fetch_bybit_payload(symbol: str, limit: int, start_ms: int | None = None, end_ms: int | None = None) -> list:
    """Fallback public 1m spot-candle source when Binance is unreachable."""
    params_dict = {"category": "spot", "symbol": symbol.upper(), "interval": "1", "limit": min(limit, 1000)}
    if start_ms is not None:
        params_dict["start"] = start_ms
    if end_ms is not None:
        params_dict["end"] = end_ms
    params = urlencode(params_dict)
    payload = _http_json(f"{BYBIT_BASE_URL}/v5/market/kline?{params}")
    if not isinstance(payload, dict) or payload.get("retCode") != 0:
        message = payload.get("retMsg", "Bybit API error") if isinstance(payload, dict) else "Bybit API error"
        raise RuntimeError(str(message))
    rows = ((payload.get("result") or {}).get("list") or [])
    if not rows:
        raise RuntimeError("Bybit returned no candle data")
    return rows


def _closed_candles(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only candles strictly before the current UTC 1m candle boundary."""
    if df.empty:
        return df
    now = pd.Timestamp(datetime.now(timezone.utc))
    current_boundary = pd.Timestamp((int(now.timestamp()) // _INTERVAL_SECONDS) * _INTERVAL_SECONDS, unit="s", tz="UTC")
    timestamps = pd.to_datetime(df["timestamp"], utc=True)
    return df.loc[timestamps < current_boundary].copy()


def _binance_frame(payload: list) -> pd.DataFrame:
    columns = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
    df = pd.DataFrame(payload, columns=columns)
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["timestamp", "open", "high", "low", "close"]].dropna().sort_values("timestamp")


def _bybit_frame(payload: list) -> pd.DataFrame:
    rows = [row[:5] for row in payload if isinstance(row, list) and len(row) >= 5]
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close"])
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["open_time"], errors="coerce"), unit="ms", utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["timestamp", "open", "high", "low", "close"]].dropna().sort_values("timestamp")


def fetch_crypto_candles(symbol: str, interval: str = INTERVAL, limit: int = 200) -> pd.DataFrame:
    if interval != INTERVAL:
        raise ValueError("Only the 1m interval is supported by the clean MMC strategy")
    symbol = symbol.strip().upper().replace("/", "")
    if not symbol:
        raise ValueError("Crypto market symbol is empty")

    errors = []
    try:
        df = _binance_frame(_fetch_binance_payload(symbol, limit))
    except Exception as exc:
        errors.append(f"Binance: {exc}")
        try:
            df = _bybit_frame(_fetch_bybit_payload(symbol, limit))
        except Exception as fallback_exc:
            errors.append(f"বিকল্প উৎস: {fallback_exc}")
            raise RuntimeError("ক্রিপ্টো বাজারের তথ্য আনা যায়নি। " + " | ".join(errors)) from fallback_exc

    df = _closed_candles(df)
    if df.empty:
        raise RuntimeError("ক্রিপ্টো বাজারে কোনো সম্পূর্ণ বন্ধ 1m candle পাওয়া যায়নি")
    return df.reset_index(drop=True)


def fetch_crypto_candle_at(symbol: str, entry_time: datetime) -> pd.DataFrame:
    """Fetch the exact historical 1m candle for a settlement timestamp."""
    symbol = symbol.strip().upper().replace("/", "")
    target = entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=timezone.utc)
    target = target.astimezone(timezone.utc).replace(second=0, microsecond=0)
    start_ms = int(target.timestamp() * 1000)
    end_ms = start_ms + (_INTERVAL_SECONDS * 1000) - 1
    errors = []
    try:
        df = _binance_frame(_fetch_binance_payload(symbol, 5, start_ms=start_ms, end_ms=end_ms))
    except Exception as exc:
        errors.append(f"Binance: {exc}")
        try:
            df = _bybit_frame(_fetch_bybit_payload(symbol, 5, start_ms=start_ms, end_ms=end_ms))
        except Exception as fallback_exc:
            errors.append(f"বিকল্প উৎস: {fallback_exc}")
            raise RuntimeError("ঐতিহাসিক ক্রিপ্টো candle আনা যায়নি। " + " | ".join(errors)) from fallback_exc
    df = df.loc[pd.to_datetime(df["timestamp"], utc=True) == pd.Timestamp(target)]
    if df.empty:
        raise RuntimeError(f"Crypto candle not found for {target.isoformat()}")
    return df.reset_index(drop=True)
