"""Quotex OTC candle data adapter.

Signal-data only: this module never places orders and never handles a
Quotex password/session token. The only supported source is the local
collector attached to the user's own Quotex browser session.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pandas as pd

from data.otc_markets import OTC_PAIRS

PERIOD = 60
# The collector publishes a candle batch roughly once per minute. Keep market
# identity and candle-cache freshness long enough to cover that cadence plus
# normal network/deploy jitter. The adapter also enforces the closed-candle
# boundary so a running candle can never reach the signal engine.
_LOCAL_TTL = 50
_LOCAL_DATA_TTL = 75
_LOCAL_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_LOCAL_ACTIVE_ASSET: tuple[float, str] | None = None
_LOCAL_LOCK = threading.Lock()


def _normalise_rows(payload: Any, default_asset: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        asset = payload.get("asset") or payload.get("symbol") or default_asset
        period = int(payload.get("period") or PERIOD)
        candles = payload.get("candles", payload.get("data"))
        if candles is None and all(k in payload for k in ("open", "high", "low", "close")):
            candles = [payload]
    else:
        asset, period, candles = default_asset, PERIOD, payload
    if isinstance(candles, dict):
        candles = list(candles.values())
    if not isinstance(candles, list):
        return rows
    for item in candles:
        try:
            if isinstance(item, dict):
                ts = item.get("timestamp", item.get("time", item.get("from")))
                op, hi, lo, cl = item.get("open"), item.get("high"), item.get("low"), item.get("close")
                item_asset = item.get("asset") or item.get("symbol") or asset
            elif isinstance(item, (list, tuple)) and len(item) >= 5:
                ts, op, cl, hi, lo = item[:5]
                item_asset = asset
            else:
                continue
            if ts is None or None in (op, hi, lo, cl):
                continue
            if isinstance(ts, (int, float)) and abs(float(ts)) > 10_000_000_000:
                ts = float(ts) / 1000.0
            stamp = pd.to_datetime(ts, unit="s" if isinstance(ts, (int, float)) else None, utc=True, errors="coerce")
            if pd.isna(stamp):
                continue
            rows.append({
                "timestamp": stamp,
                "open": float(op), "high": float(hi), "low": float(lo), "close": float(cl),
                "asset": str(item_asset), "period": period,
            })
        except (TypeError, ValueError, OverflowError):
            continue
    return rows


def ingest_local_candles(payload: Any) -> int:
    """Store candle data received from the authenticated local collector."""
    global _LOCAL_ACTIVE_ASSET
    rows = _normalise_rows(payload, str(payload.get("asset") if isinstance(payload, dict) else ""))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        asset = str(row["asset"])
        if asset in OTC_PAIRS:
            grouped.setdefault(asset, []).append(row)
    if not grouped:
        return 0
    active_asset = str(payload.get("active_asset") or "").strip() if isinstance(payload, dict) else ""
    with _LOCAL_LOCK:
        # Never cache a candle that belongs to the currently forming minute.
        # Candle timestamps are minute-start timestamps throughout this adapter.
        closed_before = pd.Timestamp.now(tz="UTC").floor("min")
        for asset, asset_rows in grouped.items():
            frame = (
                pd.DataFrame(asset_rows)
                .drop_duplicates("timestamp")
                .sort_values("timestamp")
            )
            frame = frame[frame["timestamp"] < closed_before].reset_index(drop=True)
            if frame.empty:
                continue
            old = _LOCAL_CACHE.get(asset)
            if old and time.monotonic() - old[0] < 3600:
                frame = pd.concat([old[1], frame], ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
            _LOCAL_CACHE[asset] = (time.monotonic(), frame.tail(2000).reset_index(drop=True))
        if active_asset in OTC_PAIRS:
            _LOCAL_ACTIVE_ASSET = (time.monotonic(), active_asset)
        else:
            newest = max(grouped, key=lambda name: max(row["timestamp"] for row in grouped[name]))
            _LOCAL_ACTIVE_ASSET = (time.monotonic(), newest)
    return sum(len(v) for v in grouped.values())


def local_active_asset() -> str | None:
    with _LOCAL_LOCK:
        if not _LOCAL_ACTIVE_ASSET:
            return None
        stamp, asset = _LOCAL_ACTIVE_ASSET
        return asset if time.monotonic() - stamp <= _LOCAL_TTL else None


def local_stream_status(asset: str | None = None) -> dict:
    now = time.monotonic()
    with _LOCAL_LOCK:
        names = [asset] if asset else list(_LOCAL_CACHE)
        assets = []
        for name in names:
            cached = _LOCAL_CACHE.get(name)
            if not cached:
                continue
            age = max(0.0, now - cached[0])
            assets.append({"asset": name, "fresh": age <= _LOCAL_DATA_TTL, "age_seconds": round(age, 1), "candles": len(cached[1])})
        active = _LOCAL_ACTIVE_ASSET[1] if _LOCAL_ACTIVE_ASSET and now - _LOCAL_ACTIVE_ASSET[0] <= _LOCAL_TTL else None
    return {"ok": bool(assets) and all(x["fresh"] for x in assets), "source": "Quotex local browser WebSocket collector", "active_asset": active, "assets": assets}


def _local_candles(asset: str, count: int) -> pd.DataFrame | None:
    with _LOCAL_LOCK:
        cached = _LOCAL_CACHE.get(asset)
        if not cached or time.monotonic() - cached[0] > _LOCAL_DATA_TTL:
            return None
        df = cached[1].copy(deep=True)
    if df.empty:
        return None
    # Enforce the boundary again at read time. This protects against any
    # collector/source that sends the current minute as well as stale cache
    # contents created before the ingest-side guard was added.
    closed_before = pd.Timestamp.now(tz="UTC").floor("min")
    df = df[df["timestamp"] < closed_before].reset_index(drop=True)
    return df.tail(count).reset_index(drop=True) if len(df) >= 8 else None


def fetch_quotex_candles(asset: str, interval: str = "1m", count: int = 240) -> pd.DataFrame:
    canonical = next((p for p in OTC_PAIRS if str(asset).strip().lower() == p.lower()), None)
    if not canonical:
        raise ValueError("Unsupported Quotex OTC market")
    if interval != "1m":
        raise ValueError("Quotex OTC MMC uses 1-minute candles only")
    count = max(60, min(int(count), 300))
    local = _local_candles(canonical, count)
    if local is None:
        raise RuntimeError("Quotex local WebSocket collector is not connected or has no fresh closed candles.")
    return local


def quotex_status(asset: str) -> dict:
    started = time.time()
    local = local_stream_status(asset)
    match = next((x for x in local.get("assets", []) if x["asset"] == asset), None)
    if match and match.get("fresh"):
        return {
            "ok": True, "connected": True, "asset": asset, "timeframe": "1m",
            "closed_candles": match["candles"],
            "source": "Quotex local browser WebSocket collector",
            "latency_ms": int((time.time() - started) * 1000),
        }
    return {
        "ok": False, "connected": False, "asset": asset, "timeframe": "1m",
        "error": "Quotex local WebSocket collector is not connected or data is stale.",
        "source": "Quotex local browser WebSocket collector",
        "latency_ms": int((time.time() - started) * 1000),
    }
