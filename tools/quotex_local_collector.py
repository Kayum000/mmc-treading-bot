"""Local laptop collector for a user-opened Quotex browser tab.

Signal-data-only: it does not log in, collect passwords/SSIDs, or place orders.
It attaches to Chrome DevTools Protocol (CDP), reads the browser's WebSocket
frames, normalizes supported OTC candles/quotes, builds 1-minute OHLC when
needed, and sends only candle data to the MMC Render ingest endpoint.

Environment variables:
  MMC_BOT_URL            e.g. https://mmc-treading-bot.onrender.com
  QUOTEX_INGEST_SECRET   same secret configured on Render
  CHROME_CDP_URL         default http://127.0.0.1:9222
  QUOTEX_DEBUG_VERBOSE   1 to print event names (never payloads/tokens)
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from typing import Any

import requests
import websockets

PERIOD = 60
OTC_PAIRS = {
    "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "AUDUSD_otc", "USDCAD_otc",
    "USDCHF_otc", "NZDUSD_otc", "EURJPY_otc", "GBPJPY_otc", "XAUUSD_otc",
    "USDARS_otc",
}
CDP_URL = os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9222").rstrip("/")
BOT_URL = os.getenv("MMC_BOT_URL", "https://mmc-treading-bot.onrender.com").rstrip("/")
INGEST_SECRET = os.getenv("QUOTEX_INGEST_SECRET", "").strip()
VERBOSE = os.getenv("QUOTEX_DEBUG_VERBOSE", "0").strip() == "1"


def log(message: str) -> None:
    print(f"[MMC Quotex Laptop Collector] {message}", flush=True)


def _target() -> dict[str, Any]:
    response = requests.get(f"{CDP_URL}/json/list", timeout=5)
    response.raise_for_status()
    targets = response.json()
    allowed_hosts = ("qxbroker.com", "market-qx.trade")
    candidates = [
        t for t in targets
        if t.get("type") == "page"
        and any(host in str(t.get("url", "")).lower() for host in allowed_hosts)
    ]
    if not candidates:
        candidates = [
            t for t in targets
            if t.get("type") == "page"
            and "quotex" in (str(t.get("title", "")) + str(t.get("url", ""))).lower()
        ]
    if not candidates:
        raise RuntimeError(
            "No Quotex browser tab found. Start the isolated Chrome launcher, log in, "
            "and leave the OTC chart open."
        )
    return candidates[0]


async def _cdp_command(ws, counter: list[int], method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    counter[0] += 1
    ident = counter[0]
    await ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
    while True:
        message = json.loads(await ws.recv())
        if message.get("id") == ident:
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message


def _json_after_prefix(text: str) -> Any:
    if not text:
        return None
    for idx, char in enumerate(text):
        if char in "[{":
            try:
                return json.loads(text[idx:])
            except Exception:
                return None
    return None


def _decode_socket_message(payload: str, opcode: int) -> tuple[str | None, Any]:
    if opcode == 1:
        if payload.startswith("42"):
            packet = _json_after_prefix(payload[2:])
            if isinstance(packet, list) and packet:
                return str(packet[0]), packet[1] if len(packet) > 1 else None
        if payload.startswith("45") and "_placeholder" in payload:
            packet = _json_after_prefix(payload[4:])
            if isinstance(packet, list) and packet:
                return str(packet[0]), packet[1] if len(packet) > 1 else None
        return None, None
    try:
        raw = base64.b64decode(payload)
        decoded = raw.decode("utf-8", errors="ignore")
        data = _json_after_prefix(decoded)
        if isinstance(data, list) and data and isinstance(data[0], (int, float)):
            if len(data) >= 3:
                return None, data[2]
            if len(data) == 2:
                return None, data[1]
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[0], str):
            return data[0], data[1]
        return None, data
    except Exception:
        return None, None


def _normalise_candle(payload: Any, fallback_asset: str | None = None) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        asset = payload.get("asset") or payload.get("symbol") or fallback_asset
        if all(k in payload for k in ("open", "high", "low", "close")):
            items = [payload]
        else:
            items = payload.get("candles") or payload.get("data") or []
    elif isinstance(payload, list):
        asset, items = fallback_asset, payload
    else:
        return []
    if isinstance(items, dict):
        items = list(items.values())
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        try:
            if isinstance(item, dict):
                item_asset = item.get("asset") or item.get("symbol") or asset
                ts = item.get("timestamp", item.get("time", item.get("from")))
                op, hi, lo, cl = item.get("open"), item.get("high"), item.get("low"), item.get("close")
            elif isinstance(item, (list, tuple)) and len(item) >= 5:
                item_asset = asset
                ts, op, cl, hi, lo = item[:5]
            else:
                continue
            if str(item_asset) not in OTC_PAIRS or None in (ts, op, hi, lo, cl):
                continue
            ts = float(ts)
            if ts > 10_000_000_000:
                ts /= 1000
            result.append({
                "asset": str(item_asset), "period": PERIOD, "timestamp": ts,
                "open": float(op), "high": float(hi), "low": float(lo), "close": float(cl),
            })
        except (TypeError, ValueError, OverflowError):
            continue
    return result


def _price_from_payload(payload: Any) -> tuple[str | None, float | None, float | None]:
    if not isinstance(payload, dict):
        return None, None, None
    asset = payload.get("asset") or payload.get("symbol")
    value = payload.get("price", payload.get("close"))
    ts = payload.get("timestamp", payload.get("time"))
    try:
        return str(asset) if asset else None, float(value), float(ts) if ts is not None else time.time()
    except (TypeError, ValueError):
        return None, None, None


class Collector:
    def __init__(self) -> None:
        self.partial: dict[str, dict[str, Any]] = {}
        self.session = requests.Session()
        self.last_signature = ""
        self.last_send = 0.0

    def _send(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        if not INGEST_SECRET:
            raise RuntimeError("QUOTEX_INGEST_SECRET is missing. Set the same secret on Render and locally.")
        signature = "|".join(f"{r['asset']}:{r['timestamp']}:{r['close']}" for r in rows[-5:])
        if signature == self.last_signature and time.monotonic() - self.last_send < 45:
            return
        response = self.session.post(
            f"{BOT_URL}/quotex/ingest",
            json={"sent_at": time.time(), "candles": rows},
            headers={"X-MMC-Quotex-Key": INGEST_SECRET},
            timeout=10,
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            body = response.text.strip().replace("\r", " ").replace("\n", " ")[:240]
            raise RuntimeError(f"Render ingest HTTP {response.status_code}: {body or 'empty response'}")
        try:
            data = response.json()
        except ValueError:
            body = response.text.strip().replace("\r", " ").replace("\n", " ")[:240]
            raise RuntimeError(f"Render returned non-JSON response: {body or 'empty response'}")
        if not data.get("ok"):
            raise RuntimeError(f"Render rejected candles: {data.get('error', 'unknown error')}")
        self.last_signature = signature
        self.last_send = time.monotonic()
        log(f"sent {data.get('accepted', len(rows))} candle rows to MMC")

    def _add_price(self, asset: str, price: float, ts: float) -> None:
        if asset not in OTC_PAIRS:
            return
        bucket = int(ts // PERIOD) * PERIOD
        state = self.partial.get(asset)
        if not state or state["bucket"] != bucket:
            if state:
                row = {k: v for k, v in state.items() if k != "bucket"}
                self._send([row])
            state = {
                "bucket": bucket, "asset": asset, "period": PERIOD,
                "timestamp": float(bucket), "open": price, "high": price,
                "low": price, "close": price,
            }
            self.partial[asset] = state
        else:
            state["high"] = max(state["high"], price)
            state["low"] = min(state["low"], price)
            state["close"] = price

    def handle(self, event_name: str | None, payload: Any) -> None:
        if not event_name:
            return
        name = event_name.lower()
        if VERBOSE:
            log(f"event: {event_name}")
        if name in {"candle", "candles", "history/list", "history/load", "chart_notification/get"}:
            rows = _normalise_candle(payload)
            if rows:
                self._send(rows)
            return
        if name in {"candle-generated", "quote", "quotes", "price", "tick", "instrument/price"}:
            rows = _normalise_candle(payload)
            if rows:
                self._send(rows)
                return
            asset, price, ts = _price_from_payload(payload)
            if asset and price is not None and ts is not None:
                self._add_price(asset, price, ts)


async def run() -> None:
    if not INGEST_SECRET:
        raise RuntimeError("Set QUOTEX_INGEST_SECRET before starting the collector.")
    log(f"looking for Quotex tab via {CDP_URL}")
    target = _target()
    log(f"attached to: {target.get('title') or target.get('url')}")
    ws_url = target.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("Chrome target has no webSocketDebuggerUrl. Start Chrome with remote debugging enabled.")
    async with websockets.connect(ws_url, open_timeout=10, close_timeout=5, max_size=16 * 1024 * 1024) as ws:
        counter = [0]
        await _cdp_command(
            ws, counter, "Network.enable",
            {"maxTotalBufferSize": 50 * 1024 * 1024, "maxResourceBufferSize": 5 * 1024 * 1024},
        )
        log("CDP Network capture enabled. Keep the Quotex OTC chart open.")
        collector = Collector()
        pending_event: str | None = None
        while True:
            message = json.loads(await ws.recv())
            if message.get("method") != "Network.webSocketFrameReceived":
                continue
            response = message.get("params", {}).get("response", {})
            payload = response.get("payloadData", "")
            opcode = int(response.get("opcode", 1))
            event_name, data = _decode_socket_message(payload, opcode)
            if opcode != 1 and pending_event and data is not None:
                event_name = pending_event
                pending_event = None
            if event_name and isinstance(data, dict) and data.get("_placeholder"):
                pending_event = event_name
                continue
            collector.handle(event_name, data)


def main() -> int:
    try:
        asyncio.run(run())
        return 0
    except KeyboardInterrupt:
        log("stopped")
        return 0
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
