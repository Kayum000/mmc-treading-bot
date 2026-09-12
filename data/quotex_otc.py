"""Quotex OTC candle data adapter.

Signal-data only: this module never places orders.

Two data sources are supported:
1) a local collector attached to the user's own Quotex browser session;
2) the legacy direct WebSocket path when QUOTEX_SSID/QUOTEX_SESSION_TOKEN is set.

The local-browser path is preferred because the Render service never needs the
user's Quotex session token. The collector forwards only candle/quote data.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from typing import Any

import pandas as pd
import websockets

OTC_PAIRS = (
    "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "AUDUSD_otc", "USDCAD_otc",
    "USDCHF_otc", "NZDUSD_otc", "EURJPY_otc", "GBPJPY_otc", "XAUUSD_otc",
)
PERIOD = 60
CACHE_TTL = 8
FETCH_TIMEOUT = 18
_LOCAL_TTL = 15
_CACHE: dict[tuple[str, int], tuple[float, pd.DataFrame]] = {}
_LOCAL_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_LOCAL_LOCK = threading.Lock()


def _ssid() -> str:
    return (os.getenv("QUOTEX_SSID") or os.getenv("QUOTEX_SESSION_TOKEN") or "").strip()


def _is_demo() -> bool:
    return os.getenv("QUOTEX_DEMO", "1").strip().lower() not in {"0", "false", "no"}


def _event(name: str, payload: Any = None) -> str:
    body = [name] if payload is None else [name, payload]
    return "42" + json.dumps(body, separators=(",", ":"))


def _parse_event(raw: str):
    if not isinstance(raw, str) or not raw.startswith("42"):
        return None, None
    try:
        packet = json.loads(raw[2:])
        return (packet[0], packet[1] if len(packet) > 1 else None) if isinstance(packet, list) and packet else (None, None)
    except Exception:
        return None, None


def _normalise_rows(payload: Any, default_asset: str):
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
            # Quotex sometimes emits milliseconds. Normalize both forms.
            if isinstance(ts, (int, float)) and abs(float(ts)) > 10_000_000_000:
                ts = float(ts) / 1000.0
            stamp = pd.to_datetime(ts, unit="s" if isinstance(ts, (int, float)) else None, utc=True, errors="coerce")
            if pd.isna(stamp):
                continue
            rows.append({"timestamp": stamp, "open": float(op), "high": float(hi), "low": float(lo), "close": float(cl), "asset": str(item_asset), "period": period})
        except (TypeError, ValueError, OverflowError):
            continue
    return rows


def ingest_local_candles(payload: Any) -> int:
    """Store candle data received from the local Quotex browser collector."""
    rows = _normalise_rows(payload, str(payload.get("asset") if isinstance(payload, dict) else ""))
    if not rows:
        return 0
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        asset = str(row["asset"])
        if asset in OTC_PAIRS:
            grouped.setdefault(asset, []).append(row)
    with _LOCAL_LOCK:
        for asset, asset_rows in grouped.items():
            frame = pd.DataFrame(asset_rows).drop_duplicates("timestamp").sort_values("timestamp")
            old = _LOCAL_CACHE.get(asset)
            if old and time.monotonic() - old[0] < 3600:
                frame = pd.concat([old[1], frame], ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
            _LOCAL_CACHE[asset] = (time.monotonic(), frame.tail(500).reset_index(drop=True))
    return sum(len(v) for v in grouped.values())


def local_stream_status(asset: str | None = None) -> dict:
    now = time.monotonic()
    with _LOCAL_LOCK:
        assets = [asset] if asset else list(_LOCAL_CACHE)
        rows = []
        for name in assets:
            cached = _LOCAL_CACHE.get(name)
            if not cached:
                continue
            age = max(0.0, now - cached[0])
            rows.append({"asset": name, "fresh": age <= _LOCAL_TTL, "age_seconds": round(age, 1), "candles": len(cached[1])})
    return {"ok": bool(rows) and all(x["fresh"] for x in rows), "source": "Quotex browser local collector", "assets": rows}


def _local_candles(asset: str, count: int) -> pd.DataFrame | None:
    with _LOCAL_LOCK:
        cached = _LOCAL_CACHE.get(asset)
        if not cached or time.monotonic() - cached[0] > _LOCAL_TTL:
            return None
        df = cached[1].copy(deep=True)
    if df.empty:
        return None
    boundary = pd.Timestamp((int(time.time()) // PERIOD) * PERIOD, unit="s", tz="UTC")
    df = df.loc[df["timestamp"] < boundary].tail(count).reset_index(drop=True)
    return df if len(df) >= 30 else None


async def _fetch(asset: str, count: int) -> list[dict[str, Any]]:
    ssid = _ssid()
    if not ssid:
        raise RuntimeError("Quotex browser collector is not connected. Run tools/quotex_local_collector.py on the PC where Quotex is open, or set QUOTEX_SSID as a Render Secret.")

    origin = os.getenv("QUOTEX_ORIGIN", "https://qxbroker.com").strip()
    ws_url = os.getenv("QUOTEX_WS_URL", "wss://ws2.qxbroker.com/socket.io/?EIO=3&transport=websocket").strip()
    headers = {"Origin": origin, "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
    rows: list[dict[str, Any]] = []
    pending_binary_event: str | None = None
    subscribed = False
    deadline = time.monotonic() + FETCH_TIMEOUT

    async with websockets.connect(ws_url, additional_headers=headers, origin=origin, open_timeout=8, close_timeout=3, ping_interval=None, max_size=4 * 1024 * 1024) as ws:
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, deadline - time.monotonic()))
            if raw == "2":
                await ws.send("3")
                continue
            if isinstance(raw, (bytes, bytearray)):
                if pending_binary_event:
                    try:
                        rows.extend(_normalise_rows(json.loads(bytes(raw).decode("utf-8", errors="ignore")), asset))
                    except Exception:
                        pass
                    pending_binary_event = None
                continue
            if not isinstance(raw, str):
                continue
            if raw.startswith("0") or raw == "40":
                if raw == "40":
                    await ws.send(_event("authorization", {"session": ssid, "isDemo": 1 if _is_demo() else 0, "tournamentId": 0}))
                continue

            event_name, payload = _parse_event(raw)
            if not event_name:
                continue
            event_text = str(event_name).lower()
            if "reject" in event_text or event_text in {"auth_error", "authorization/reject"}:
                raise RuntimeError("Quotex SSID rejected or expired; refresh the session token.")
            if event_text in {"s_authorization", "authorization"} and not subscribed:
                subscribed = True
                await ws.send(_event("instruments/update", {"asset": asset, "period": PERIOD}))
                await ws.send(_event("history/load", {"asset": asset, "index": 0, "period": PERIOD, "time": int(time.time()), "offset": max(3600, count * PERIOD)}))
            if isinstance(payload, dict) and payload.get("_placeholder"):
                pending_binary_event = str(event_name)
                continue
            if event_text in {"candle", "candles", "history/list", "history/load", "candle-generated", "chart_notification/get"}:
                rows.extend(_normalise_rows(payload, asset))
                if len(rows) >= max(60, count):
                    break

    return rows


def fetch_quotex_candles(asset: str, interval: str = "1m", count: int = 240) -> pd.DataFrame:
    canonical = next((p for p in OTC_PAIRS if str(asset).strip().lower() == p.lower()), None)
    if not canonical:
        raise ValueError("Unsupported Quotex OTC market")
    if interval != "1m":
        raise ValueError("Quotex OTC MMC uses 1-minute candles only")
    count = max(60, min(int(count), 300))

    # Prefer the real browser stream. Render does not need the Quotex token when
    # the local collector is running.
    local = _local_candles(canonical, count)
    if local is not None:
        return local

    key = (canonical, count)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        return cached[1].copy(deep=True)
    try:
        rows = asyncio.run(_fetch(canonical, count))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Quotex OTC data connection failed: {type(exc).__name__}: {exc}") from exc
    if not rows:
        raise RuntimeError(f"Quotex returned no candle data for {canonical}.")
    df = pd.DataFrame(rows).drop_duplicates("timestamp").sort_values("timestamp")
    boundary = pd.Timestamp((int(time.time()) // PERIOD) * PERIOD, unit="s", tz="UTC")
    df = df.loc[df["timestamp"] < boundary].tail(count).reset_index(drop=True)
    if len(df) < 30:
        raise RuntimeError(f"Quotex returned only {len(df)} closed 1m candles for {canonical}.")
    _CACHE[key] = (time.monotonic(), df)
    return df.copy(deep=True)


def quotex_status(asset: str) -> dict:
    started = time.time()
    local = local_stream_status(asset)
    if local.get("ok"):
        match = next((x for x in local.get("assets", []) if x["asset"] == asset), None)
        return {"ok": True, "connected": True, "asset": asset, "timeframe": "1m", "closed_candles": match["candles"] if match else 0, "source": "Quotex browser local collector", "latency_ms": int((time.time() - started) * 1000)}
    try:
        df = fetch_quotex_candles(asset, "1m", 80)
        return {"ok": True, "connected": True, "asset": asset, "timeframe": "1m", "closed_candles": len(df), "latest_closed_candle": pd.Timestamp(df.iloc[-1]["timestamp"]).strftime("%d %b %Y, %H:%M:%S UTC"), "source": "Quotex OTC WebSocket", "latency_ms": int((time.time() - started) * 1000)}
    except Exception as exc:
        return {"ok": False, "connected": False, "asset": asset, "timeframe": "1m", "error": str(exc), "source": "Quotex browser local collector / WebSocket", "latency_ms": int((time.time() - started) * 1000)}
