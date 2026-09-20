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

from data.otc_markets import OTC_PAIRS, normalize_detected_market

PERIOD = 60
# The collector publishes a candle batch roughly once per minute. Keep market
# identity and candle-cache freshness long enough to cover that cadence plus
# normal network/deploy jitter. The adapter also enforces the closed-candle
# boundary so a running candle can never reach the signal engine.
_LOCAL_TTL = 50
_LOCAL_DATA_TTL = 75
_LOCAL_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_LOCAL_TICK_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
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
        raw_asset = str(row["asset"]).strip()
        asset = raw_asset if raw_asset in OTC_PAIRS else normalize_detected_market(raw_asset)
        if asset in OTC_PAIRS:
            row["asset"] = asset
            grouped.setdefault(asset, []).append(row)
    if not grouped:
        return 0
    active_raw = str(payload.get("active_asset") or "").strip() if isinstance(payload, dict) else ""
    active_asset = active_raw if active_raw in OTC_PAIRS else normalize_detected_market(active_raw)
    sent_at = payload.get("sent_at") if isinstance(payload, dict) else None
    try:
        sent_at_utc = pd.to_datetime(float(sent_at), unit="s", utc=True) if sent_at is not None else None
    except (TypeError, ValueError, OverflowError):
        sent_at_utc = None
    with _LOCAL_LOCK:
        # A candle is closed only after its full 60-second period has elapsed.
        # Prefer the collector's sent_at clock so a small Render/collector clock
        # skew cannot accidentally admit the current running candle.
        server_closed_before = pd.Timestamp.now(tz="UTC").floor("min")
        closed_before = sent_at_utc if sent_at_utc is not None else server_closed_before
        accepted = 0
        # Refresh the selected/visible OTC market as soon as a valid market
        # identity arrives. The collector may send a still-forming candle;
        # that candle must be rejected, but it must NOT make the active market
        # disappear while we still have a fresh closed-candle cache for it.
        active_candidates = [name for name in grouped if name in OTC_PAIRS]
        for candidate in active_candidates:
            cached = _LOCAL_CACHE.get(candidate)
            if cached and time.monotonic() - cached[0] <= _LOCAL_DATA_TTL:
                _LOCAL_ACTIVE_ASSET = (time.monotonic(), candidate)
                break

        for asset, asset_rows in grouped.items():
            frame = (
                pd.DataFrame(asset_rows)
                .drop_duplicates("timestamp")
                .sort_values("timestamp")
            )
            frame = frame[frame["timestamp"] + pd.Timedelta(seconds=PERIOD) <= closed_before].reset_index(drop=True)
            if frame.empty:
                continue
            accepted += len(frame)
            old = _LOCAL_CACHE.get(asset)
            if old and time.monotonic() - old[0] < 3600:
                frame = pd.concat([old[1], frame], ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
            _LOCAL_CACHE[asset] = (time.monotonic(), frame.tail(2000).reset_index(drop=True))
        if active_asset in OTC_PAIRS and active_asset in _LOCAL_CACHE:
            _LOCAL_ACTIVE_ASSET = (time.monotonic(), active_asset)
        elif not active_candidates and accepted:
            newest = max(
                (name for name in grouped if name in _LOCAL_CACHE),
                key=lambda name: _LOCAL_CACHE[name][1]["timestamp"].iloc[-1],
            )
            _LOCAL_ACTIVE_ASSET = (time.monotonic(), newest)
    return accepted


def ingest_local_ticks(payload: Any) -> int:
    """Store fresh OTC tick/quote data from the user's local Quotex collector."""
    global _LOCAL_ACTIVE_ASSET
    if not isinstance(payload, dict):
        return 0
    raw_asset = str(payload.get("asset") or "").strip()
    asset = raw_asset if raw_asset in OTC_PAIRS else normalize_detected_market(raw_asset)
    if asset not in OTC_PAIRS:
        return 0
    rows = payload.get("ticks") or payload.get("quotes") or []
    if not isinstance(rows, list):
        return 0
    out = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            ts = float(item.get("timestamp", item.get("time")))
            price = float(item.get("price", item.get("close")))
        except (TypeError, ValueError):
            continue
        if ts > 10_000_000_000:
            ts /= 1000.0
        if not all(v == v and abs(v) != float("inf") for v in (ts, price)):
            continue
        stamp = pd.to_datetime(ts, unit="s", utc=True, errors="coerce")
        if pd.isna(stamp):
            continue
        spread = max(abs(price) * 0.00001, 0.00001)
        out.append({"timestamp": stamp, "askPrice": price + spread / 2.0, "bidPrice": price - spread / 2.0})
    if not out:
        return 0
    frame = pd.DataFrame(out).drop_duplicates("timestamp").sort_values("timestamp")
    now = time.monotonic()
    with _LOCAL_LOCK:
        old = _LOCAL_TICK_CACHE.get(asset)
        if old and now - old[0] < 120:
            frame = pd.concat([old[1], frame], ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
        _LOCAL_TICK_CACHE[asset] = (now, frame.tail(1000).reset_index(drop=True))
        _LOCAL_ACTIVE_ASSET = (now, asset)
    return len(out)


def local_ticks(asset: str, count: int = 1000) -> pd.DataFrame:
    with _LOCAL_LOCK:
        cached = _LOCAL_TICK_CACHE.get(asset)
        if not cached or time.monotonic() - cached[0] > 75:
            return pd.DataFrame(columns=["timestamp", "askPrice", "bidPrice"])
        return cached[1].tail(max(1, min(int(count), 1000))).copy(deep=True).reset_index(drop=True)


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
            latest_closed = None
            if not cached[1].empty:
                latest_closed = cached[1]["timestamp"].iloc[-1].isoformat()
            assets.append({
                "asset": name,
                "fresh": age <= _LOCAL_DATA_TTL,
                "age_seconds": round(age, 1),
                "candles": len(cached[1]),
                "latest_closed": latest_closed,
            })
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
    # Enforce the full candle-age boundary again at read time. This protects
    # against stale cache contents or a collector/source that sends a running
    # candle after ingest.
    closed_before = pd.Timestamp.now(tz="UTC").floor("min")
    df = df[df["timestamp"] + pd.Timedelta(seconds=PERIOD) <= closed_before].reset_index(drop=True)
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


def local_candles_payload(asset: str | None = None, count: int = 240) -> dict:
    """Return fresh closed OTC candles for the authenticated chart/performance UI."""
    chosen = asset or local_active_asset()
    if not chosen or chosen not in OTC_PAIRS:
        return {"ok": False, "asset": chosen, "candles": []}
    frame = _local_candles(chosen, max(8, min(int(count), 300)))
    if frame is None:
        return {"ok": False, "asset": chosen, "candles": []}
    candles = []
    for _, row in frame.iterrows():
        candles.append({
            "timestamp": row["timestamp"].isoformat(),
            "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]),
        })
    return {"ok": True, "asset": chosen, "candles": candles, "source": "Quotex local browser WebSocket collector"}

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
