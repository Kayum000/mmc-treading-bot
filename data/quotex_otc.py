"""Quotex OTC 1-minute candle data adapter (data only; no trade execution)."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path

import pandas as pd

OTC_PAIRS = (
    "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "AUDUSD_otc", "USDCAD_otc",
    "USDCHF_otc", "NZDUSD_otc", "EURJPY_otc", "GBPJPY_otc", "XAUUSD_otc",
)
_PERIOD = 60
_LOCK = threading.Lock()
_CACHE: dict[tuple[str, int], tuple[float, pd.DataFrame]] = {}
_BLOCK_UNTIL = 0.0
_BLOCK_ERROR = ""
_LOG = logging.getLogger(__name__)


def _rss_mb() -> float:
    try:
        for line in Path("/proc/self/status").read_text(errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def _client():
    try:
        import setuptools  # noqa: F401
        from quotexpy import Quotex
    except Exception as exc:
        raise RuntimeError(f"QuotexPy load failed: {type(exc).__name__}: {exc}") from exc
    email = os.getenv("QUOTEX_EMAIL", "").strip()
    password = os.getenv("QUOTEX_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("Quotex OTC চালাতে QUOTEX_EMAIL/QUOTEX_PASSWORD সেট করতে হবে।")
    kwargs = {
        "lang": os.getenv("QUOTEX_LANG", "en"),
        "time_period": _PERIOD,
    }
    return Quotex(email=email, password=password, **kwargs)


def _rows(payload):
    if isinstance(payload, dict):
        payload = payload.get("data", payload.get("candles", payload.get("values", [])))
    if isinstance(payload, dict):
        payload = list(payload.values())
    if not isinstance(payload, list):
        return []
    out = []
    for item in payload:
        if isinstance(item, dict):
            ts = item.get("time", item.get("timestamp", item.get("from")))
            op, hi, lo, cl = item.get("open"), item.get("high"), item.get("low"), item.get("close")
        elif isinstance(item, (list, tuple)) and len(item) >= 5:
            ts, op, cl, hi, lo = item[:5]
        else:
            continue
        try:
            ts = float(ts)
            if ts > 10_000_000_000:
                ts /= 1000.0
            out.append({
                "timestamp": pd.Timestamp.fromtimestamp(ts, tz="UTC"),
                "open": float(op), "high": float(hi), "low": float(lo), "close": float(cl),
            })
        except (TypeError, ValueError, OSError):
            continue
    return out


async def _connect_and_get(client, asset: str, offset: int):
    """Keep connect() and get_candles() on the same asyncio loop."""
    connected = await client.connect()
    if not connected:
        raise RuntimeError("Quotex connection failed")
    # QuotexPy's candle API expects the end timestamp separately from the
    # look-back offset. Passing the offset as the second positional argument
    # makes the request start around the Unix epoch and returns no usable data.
    return await asyncio.wait_for(
        client.get_candles(
            asset=asset,
            end_from_time=int(time.time()),
            offset=offset,
            period=_PERIOD,
        ),
        timeout=35,
    )


def fetch_quotex_candles(asset: str, interval: str = "1m", count: int = 240) -> pd.DataFrame:
    global _BLOCK_UNTIL, _BLOCK_ERROR
    asset = str(asset).strip()
    canonical = next((p for p in OTC_PAIRS if p.lower() == asset.lower()), None)
    if not canonical:
        raise ValueError("Unsupported Quotex OTC market")
    if interval != "1m":
        raise ValueError("Quotex OTC MMC uses 1-minute candles only")
    key = (canonical, int(count))
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < 15:
        return cached[1].copy(deep=True)
    if now < _BLOCK_UNTIL:
        raise RuntimeError(_BLOCK_ERROR or "Quotex access is temporarily blocked; retry later.")
    with _LOCK:
        now = time.monotonic()
        cached = _CACHE.get(key)
        if cached and now - cached[0] < 15:
            return cached[1].copy(deep=True)
        max_rss = float(os.getenv("QUOTEX_MAX_RSS_MB", "430"))
        if _rss_mb() >= max_rss:
            raise RuntimeError("Quotex OTC temporarily paused by memory guard.")
        client = None
        try:
            client = _client()
            # Quotex's offset is measured in seconds. Ask for enough recent
            # history for the 1m/5m/15m analysis while allowing the library's
            # own response-size limit to apply.
            offset = _PERIOD * min(max(int(count) + 20, 180), 12000)
            payload = asyncio.run(_connect_and_get(client, canonical, offset))
            rows = _rows(payload)
            if not rows:
                raise RuntimeError(f"Quotex returned no candle data for {canonical}.")
            df = pd.DataFrame(rows).drop_duplicates("timestamp").sort_values("timestamp")
            boundary = pd.Timestamp((int(time.time()) // _PERIOD) * _PERIOD, unit="s", tz="UTC")
            df = df.loc[df["timestamp"] < boundary].tail(int(count)).reset_index(drop=True)
            if len(df) < 60:
                raise RuntimeError(f"Quotex returned only {len(df)} closed 1m candles for {canonical}.")
            _BLOCK_UNTIL = 0.0
            _BLOCK_ERROR = ""
            _CACHE[key] = (time.monotonic(), df)
            return df.copy(deep=True)
        except Exception as exc:
            _LOG.exception("Quotex OTC fetch failed for %s: %s", canonical, exc)
            text = str(exc).lower()
            if "403" in text or "forbidden" in text or "cloudflare" in text:
                _BLOCK_ERROR = "Quotex returned an access/Cloudflare block from the server."
                _BLOCK_UNTIL = time.monotonic() + 90
            raise
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass


def quotex_status(asset: str) -> dict:
    started = time.time()
    try:
        df = fetch_quotex_candles(asset, "1m", 80)
        return {
            "ok": True, "connected": True, "asset": asset, "timeframe": "1m",
            "closed_candles": len(df),
            "latest_closed_candle": pd.Timestamp(df.iloc[-1]["timestamp"]).strftime("%d %b %Y, %H:%M:%S UTC"),
            "source": "Quotex OTC", "latency_ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        return {
            "ok": False, "connected": False, "asset": asset, "timeframe": "1m",
            "error": str(exc), "source": "Quotex OTC", "latency_ms": int((time.time() - started) * 1000),
        }
