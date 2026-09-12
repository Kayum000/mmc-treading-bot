"""Quotex OTC candle data adapter.

Signal-data only: this module never places orders. It uses a single short-lived
WebSocket connection with a pre-authenticated Quotex SSID, caches recent data,
and fails fast when the session is missing or stale.
"""
from __future__ import annotations

import asyncio
import json
import os
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
_CACHE: dict[tuple[str, int], tuple[float, pd.DataFrame]] = {}


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
            stamp = pd.to_datetime(ts, unit="s" if isinstance(ts, (int, float)) else None, utc=True, errors="coerce")
            if pd.isna(stamp):
                continue
            rows.append({"timestamp": stamp, "open": float(op), "high": float(hi), "low": float(lo), "close": float(cl), "asset": str(item_asset), "period": period})
        except (TypeError, ValueError, OverflowError):
            continue
    return rows


async def _fetch(asset: str, count: int) -> list[dict[str, Any]]:
    ssid = _ssid()
    if not ssid:
        raise RuntimeError("Quotex OTC চালাতে QUOTEX_SSID বা QUOTEX_SESSION_TOKEN Render Secret-এ সেট করতে হবে।")

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

            # Authorization can arrive as a normal event or as a 451 binary placeholder.
            # Subscribe immediately; waiting for the profile payload would race the history request.
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
    try:
        df = fetch_quotex_candles(asset, "1m", 80)
        return {"ok": True, "connected": True, "asset": asset, "timeframe": "1m", "closed_candles": len(df), "latest_closed_candle": pd.Timestamp(df.iloc[-1]["timestamp"]).strftime("%d %b %Y, %H:%M:%S UTC"), "source": "Quotex OTC WebSocket", "latency_ms": int((time.time() - started) * 1000)}
    except Exception as exc:
        return {"ok": False, "connected": False, "asset": asset, "timeframe": "1m", "error": str(exc), "source": "Quotex OTC WebSocket", "latency_ms": int((time.time() - started) * 1000)}
