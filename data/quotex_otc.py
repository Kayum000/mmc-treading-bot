"""Quotex OTC 1-minute candle data adapter.

Data-only integration: this module never places trades. Credentials are read
from environment variables and the returned frame contains closed OHLC candles.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import time

import pandas as pd

OTC_PAIRS = [
    "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "AUDUSD_otc", "USDCAD_otc",
    "USDCHF_otc", "NZDUSD_otc", "EURJPY_otc", "GBPJPY_otc", "XAUUSD_otc",
]
_PERIOD = 60


def _run(value):
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def _client():
    try:
        from quotexapi.stable_api import Quotex
    except ImportError as exc:
        raise RuntimeError("Quotex data library is not installed on the server.") from exc
    email = os.getenv("QUOTEX_EMAIL", "").strip()
    password = os.getenv("QUOTEX_PASSWORD", "")
    ssid = os.getenv("QUOTEX_SSID", "").strip()
    email_pass = os.getenv("QUOTEX_EMAIL_PASS", "").strip()
    if not ssid and (not email or not password):
        raise RuntimeError("Quotex OTC চালাতে QUOTEX_EMAIL/QUOTEX_PASSWORD বা QUOTEX_SSID সেট করুন।")
    kwargs = {"lang": os.getenv("QUOTEX_LANG", "en")}
    if ssid:
        kwargs["set_ssid"] = ssid
    else:
        kwargs.update(email=email, password=password)
        if email_pass:
            kwargs["email_pass"] = email_pass
    return Quotex(**kwargs)


def _normalise_rows(payload):
    if isinstance(payload, dict):
        payload = payload.get("data", payload.get("candles", payload.get("values", [])))
    if isinstance(payload, dict):
        payload = list(payload.values())
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload:
        if isinstance(item, dict):
            ts = item.get("time", item.get("timestamp", item.get("from")))
            op, hi, lo, cl = item.get("open"), item.get("high"), item.get("low"), item.get("close")
        elif isinstance(item, (list, tuple)) and len(item) >= 5:
            ts, op, cl, hi, lo = item[:5]
        else:
            continue
        try:
            ts_num = float(ts)
            if ts_num > 10_000_000_000:
                ts_num /= 1000.0
            rows.append({
                "timestamp": pd.Timestamp.fromtimestamp(ts_num, tz="UTC"),
                "open": float(op), "high": float(hi), "low": float(lo), "close": float(cl),
            })
        except (TypeError, ValueError, OSError):
            continue
    return rows


def _fetch_sync(asset: str, count: int = 200):
    client = _client()
    try:
        check = _run(client.connect())
        ok = check[0] if isinstance(check, tuple) else bool(check)
        if not ok:
            reason = check[1] if isinstance(check, tuple) and len(check) > 1 else "unknown connection error"
            raise RuntimeError(f"Quotex connection failed: {reason}")
        end_ts = time.time()
        offset = _PERIOD * max(count + 20, 220)
        payload = _run(client.get_candles(asset, end_ts, offset, _PERIOD))
        rows = _normalise_rows(payload)
        if not rows:
            raise RuntimeError(f"Quotex returned no candle data for {asset}.")
        df = pd.DataFrame(rows).drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        boundary = pd.Timestamp((int(time.time()) // _PERIOD) * _PERIOD, unit="s", tz="UTC")
        df = df.loc[df["timestamp"] < boundary].tail(count).reset_index(drop=True)
        if len(df) < 27:
            raise RuntimeError(f"Quotex returned only {len(df)} closed 1m candles for {asset}; at least 27 are required.")
        return df
    finally:
        try:
            _run(client.close())
        except Exception:
            pass


def fetch_quotex_candles(asset: str, interval: str = "1m", count: int = 200) -> pd.DataFrame:
    asset = str(asset).strip()
    if asset not in OTC_PAIRS:
        raise ValueError("Unsupported Quotex OTC market")
    if interval != "1m":
        raise ValueError("Only the 1m timeframe is supported for Quotex OTC MMC")
    return _fetch_sync(asset, count=count)


def quotex_status(asset: str) -> dict:
    started = time.time()
    try:
        df = fetch_quotex_candles(asset, "1m", 40)
        latest = pd.Timestamp(df.iloc[-1]["timestamp"]).strftime("%d %b %Y, %H:%M:%S UTC")
        return {"ok": True, "connected": True, "asset": asset, "timeframe": "1m", "closed_candles": len(df), "latest_closed_candle": latest, "source": "Quotex OTC", "latency_ms": int((time.time() - started) * 1000)}
    except Exception as exc:
        return {"ok": False, "connected": False, "asset": asset, "timeframe": "1m", "error": str(exc), "source": "Quotex OTC", "latency_ms": int((time.time() - started) * 1000)}
