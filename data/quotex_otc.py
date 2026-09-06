"""Quotex OTC 1-minute candle data adapter.

Data-only integration: this module never places trades. Credentials are read
from environment variables and the returned frame contains closed OHLC candles.

The OTC adapter intentionally uses the WebSocket-based ``pyquotex`` client.
The previous ``quotexpy==1.40.7`` browser/Selenium path could start Chromium on
Render and push the single 512 MB service over its memory limit. Keeping the
browser out of this module also removes the Chrome/ChromeDriver compatibility
failure from the signal-data path.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
import threading

import pandas as pd

OTC_PAIRS = [
    "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "AUDUSD_otc", "USDCAD_otc",
    "USDCHF_otc", "NZDUSD_otc", "EURJPY_otc", "GBPJPY_otc", "XAUUSD_otc",
]
_PERIOD = 60
_QUOTEX_LOCK = threading.Lock()
_CANDLE_CACHE: dict[tuple[str, int], tuple[float, pd.DataFrame]] = {}
_CANDLE_CACHE_TTL = 15.0
_STATUS_CACHE: dict[str, tuple[float, dict]] = {}
_STATUS_CACHE_TTL = 15.0


def _memory_rss_mb() -> float:
    """Return this process RSS in MB without adding another dependency."""
    try:
        status = Path("/proc/self/status").read_text(errors="ignore")
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def _run(value, timeout: float | None = None):
    """Run one pyquotex coroutine in an isolated event loop."""
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        async def _wait():
            if timeout is None:
                return await value
            return await asyncio.wait_for(value, timeout=timeout)
        return asyncio.run(_wait())
    return value


def _client():
    """Create the lightweight WebSocket client; no Chromium/Selenium is used."""
    try:
        from pyquotex.stable_api import Quotex
    except Exception as exc:
        raise RuntimeError(
            f"PyQuotex WebSocket library load failed: {type(exc).__name__}: {exc}"
        ) from exc

    email = os.getenv("QUOTEX_EMAIL", "").strip()
    password = os.getenv("QUOTEX_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("Quotex OTC চালাতে QUOTEX_EMAIL/QUOTEX_PASSWORD সেট করুন।")

    # Keep session data in /tmp so credentials/session state do not grow the
    # repository working tree. pyquotex uses this as local session storage;
    # it is not a browser profile.
    session_root = "/tmp/mmc-quotex"
    os.makedirs(session_root, exist_ok=True)
    return Quotex(
        email=email,
        password=password,
        lang=os.getenv("QUOTEX_LANG", "en"),
        root_path=session_root,
        user_data_dir="session",
        period_default=_PERIOD,
    )


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
    canonical = next((item for item in OTC_PAIRS if item.lower() == str(asset).strip().lower()), "")
    if not canonical:
        raise ValueError("Unsupported Quotex OTC market")
    cache_key = (canonical, int(count))
    now = time.monotonic()
    cached = _CANDLE_CACHE.get(cache_key)
    if cached and now - cached[0] < _CANDLE_CACHE_TTL:
        return cached[1].copy(deep=True)

    # Serialise only the Quotex network client. This avoids overlapping login /
    # websocket sessions while preserving the rest of the Flask application.
    with _QUOTEX_LOCK:
        now = time.monotonic()
        cached = _CANDLE_CACHE.get(cache_key)
        if cached and now - cached[0] < _CANDLE_CACHE_TTL:
            return cached[1].copy(deep=True)

        # Keep a guard against a bad upstream response/restart loop consuming
        # the remaining Render memory. Unlike the old browser path, this should
        # normally stay far below the 512 MB service limit.
        rss = _memory_rss_mb()
        max_rss = float(os.getenv("QUOTEX_MAX_RSS_MB", "430"))
        if rss >= max_rss:
            raise RuntimeError(
                f"Quotex temporarily paused: service memory is {rss:.0f} MB "
                f"(guard {max_rss:.0f} MB)."
            )

        client = None
        try:
            client = _client()
            check = _run(client.connect(), timeout=35)
            ok = check[0] if isinstance(check, tuple) else bool(check)
            if not ok:
                reason = check[1] if isinstance(check, tuple) and len(check) > 1 else "unknown connection error"
                raise RuntimeError(f"Quotex connection failed: {reason}")

            # pyquotex's candle API uses seconds for offset/period. Request a
            # small window because the signal engine only needs the latest
            # closed candles; this avoids unnecessary WebSocket payloads.
            offset = _PERIOD * max(count + 20, 220)
            payload = _run(
                client.get_candles(
                    asset=canonical,
                    end_from_time=time.time(),
                    offset=offset,
                    period=_PERIOD,
                ),
                timeout=25,
            )
            rows = _normalise_rows(payload)
            if not rows:
                raise RuntimeError(f"Quotex returned no candle data for {canonical}.")

            df = pd.DataFrame(rows).drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
            boundary = pd.Timestamp((int(time.time()) // _PERIOD) * _PERIOD, unit="s", tz="UTC")
            df = df.loc[df["timestamp"] < boundary].tail(count).reset_index(drop=True)
            if len(df) < 27:
                raise RuntimeError(
                    f"Quotex returned only {len(df)} closed 1m candles for {canonical}; "
                    "at least 27 are required."
                )
            _CANDLE_CACHE[cache_key] = (time.monotonic(), df)
            return df.copy(deep=True)
        finally:
            if client is not None:
                try:
                    _run(client.close(), timeout=8)
                except Exception:
                    pass


def fetch_quotex_candles(asset: str, interval: str = "1m", count: int = 200) -> pd.DataFrame:
    asset = str(asset).strip()
    canonical = next((item for item in OTC_PAIRS if item.lower() == asset.lower()), "")
    if not canonical:
        raise ValueError("Unsupported Quotex OTC market")
    if interval != "1m":
        raise ValueError("Only the 1m timeframe is supported for Quotex OTC MMC")
    return _fetch_sync(canonical, count=count)


def quotex_status(asset: str) -> dict:
    canonical = next((item for item in OTC_PAIRS if item.lower() == str(asset).strip().lower()), "")
    if not canonical:
        return {
            "ok": False, "connected": False, "asset": asset, "timeframe": "1m",
            "error": "Unsupported Quotex OTC market", "source": "Quotex OTC", "latency_ms": 0,
        }

    cache_key = canonical
    now = time.monotonic()
    cached = _STATUS_CACHE.get(cache_key)
    if cached and now - cached[0] < _STATUS_CACHE_TTL:
        return dict(cached[1])

    started = time.time()
    try:
        df = fetch_quotex_candles(canonical, "1m", 40)
        result = {
            "ok": True,
            "connected": True,
            "asset": canonical,
            "timeframe": "1m",
            "closed_candles": len(df),
            "latest_closed_candle": pd.Timestamp(df.iloc[-1]["timestamp"]).strftime("%d %b %Y, %H:%M:%S UTC"),
            "source": "Quotex OTC",
            "latency_ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        result = {
            "ok": False,
            "connected": False,
            "asset": canonical,
            "timeframe": "1m",
            "error": str(exc),
            "source": "Quotex OTC",
            "latency_ms": int((time.time() - started) * 1000),
        }
    _STATUS_CACHE[cache_key] = (time.monotonic(), result)
    return dict(result)
