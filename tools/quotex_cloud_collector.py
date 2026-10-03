"""Cloud Quotex collector for both Quotex Real Market and OTC data.

Runs headless Chromium on Render, captures Quotex WebSocket frames, normalizes
closed 1-minute candles/ticks, and forwards them to the existing MMC ingest
endpoints. Signal-data-only: it never places trades.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import requests
from playwright.async_api import async_playwright

from data.otc_markets import OTC_PAIRS

BOT_URL = os.getenv("MMC_BOT_URL", "https://mmc-treading-bot.onrender.com").rstrip("/")
INGEST_SECRET = os.getenv("QUOTEX_INGEST_SECRET", "").strip()
QUOTEX_URL = os.getenv("QUOTEX_URL", "https://market-qx.trade/en/demo-trade")
STORAGE_STATE_B64 = os.getenv("QUOTEX_STORAGE_STATE_B64", "").strip()
LOGIN_EMAIL = os.getenv("QUOTEX_LOGIN_EMAIL", "").strip()
LOGIN_PASSWORD = os.getenv("QUOTEX_LOGIN_PASSWORD", "").strip()
REAL_ASSET = os.getenv("QUOTEX_REAL_ASSET", "AUDCAD").strip().upper()
HEALTH_PORT = int(os.getenv("PORT", os.getenv("QUOTEX_COLLECTOR_HEALTH_PORT", "8765")))
PERIOD = 60


def log(message: str) -> None:
    print(f"[MMC Quotex Cloud Collector] {message}", flush=True)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        body = b'{"ok":true,"service":"quotex-cloud-collector","feeds":["otc","real"]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        return


def start_health_server() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"health endpoint listening on :{HEALTH_PORT}/health")


def json_after_prefix(text: str) -> Any:
    if not text:
        return None
    for idx, char in enumerate(text):
        if char in "[{":
            try:
                return json.loads(text[idx:])
            except Exception:
                return None
    return None


def decode_socket_message(payload: str) -> tuple[str | None, Any]:
    if payload.startswith("42"):
        packet = json_after_prefix(payload[2:])
        if isinstance(packet, list) and packet:
            return str(packet[0]), packet[1] if len(packet) > 1 else None
    if payload.startswith("45") and "_placeholder" in payload:
        packet = json_after_prefix(payload[4:])
        if isinstance(packet, list) and packet:
            return str(packet[0]), packet[1] if len(packet) > 1 else None
    packet = json_after_prefix(payload)
    if isinstance(packet, list) and packet and isinstance(packet[0], str):
        return packet[0], packet[1] if len(packet) > 1 else None
    if isinstance(packet, list) and packet and isinstance(packet[0], list):
        return "quotes/stream", packet
    return None, packet


def price_from_payload(payload: Any) -> tuple[str | None, float | None, float]:
    if isinstance(payload, dict):
        asset = payload.get("asset") or payload.get("symbol")
        value = payload.get("price", payload.get("close"))
        ts = payload.get("timestamp", payload.get("time")) or time.time()
        try:
            return str(asset) if asset else None, float(value), float(ts)
        except (TypeError, ValueError):
            return None, None, time.time()
    if isinstance(payload, list) and len(payload) >= 3 and isinstance(payload[0], str):
        try:
            return str(payload[0]), float(payload[2]), float(payload[1])
        except (TypeError, ValueError):
            return None, None, time.time()
    return None, None, time.time()


def normalise_candles(payload: Any, fallback_asset: str | None = None) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        asset = payload.get("asset") or payload.get("symbol") or fallback_asset
        if all(k in payload for k in ("open", "high", "low", "close")):
            items = [payload]
        else:
            items = payload.get("candles") or payload.get("data") or payload.get("history") or []
    elif isinstance(payload, list):
        asset, items = fallback_asset, payload
    else:
        return []
    if isinstance(items, dict):
        items = list(items.values())
    result = []
    for item in items if isinstance(items, list) else []:
        try:
            if isinstance(item, dict):
                a = item.get("asset") or item.get("symbol") or asset
                ts = item.get("timestamp", item.get("time", item.get("from")))
                op, hi, lo, cl = item.get("open"), item.get("high"), item.get("low"), item.get("close")
            elif isinstance(item, (list, tuple)) and len(item) >= 5:
                a = asset
                ts, op, cl, hi, lo = item[:5]
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                a = asset
                ts, cl = item[:2]
                op = hi = lo = cl
            else:
                continue
            if not a or None in (ts, op, hi, lo, cl):
                continue
            ts = float(ts)
            if ts > 10_000_000_000:
                ts /= 1000
            result.append({
                "asset": str(a), "period": PERIOD, "timestamp": ts,
                "open": float(op), "high": float(hi), "low": float(lo), "close": float(cl),
            })
        except (TypeError, ValueError, OverflowError):
            continue
    return result


class Collector:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.partial: dict[str, dict[str, Any]] = {}
        self.closed_history: dict[str, dict[int, dict[str, Any]]] = {}
        self.last_signature = ""
        self.last_send = 0.0
        self.last_quote_send: dict[str, float] = {}
        self.last_partial_flush_bucket: dict[str, int] = {}

    def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not INGEST_SECRET:
            raise RuntimeError("QUOTEX_INGEST_SECRET is missing")
        response = self.session.post(
            f"{BOT_URL}{endpoint}", json=payload,
            headers={"X-MMC-Quotex-Key": INGEST_SECRET},
            timeout=15, allow_redirects=False,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "ingest rejected data"))
        return data

    def remember_closed(self, rows: list[dict[str, Any]]) -> None:
        boundary = int(time.time() // PERIOD) * PERIOD
        for row in rows:
            try:
                asset = str(row["asset"])
                bucket = int(float(row["timestamp"]) // PERIOD) * PERIOD
            except (KeyError, TypeError, ValueError):
                continue
            if bucket >= boundary:
                continue
            history = self.closed_history.setdefault(asset, {})
            history[bucket] = {k: v for k, v in row.items() if k != "bucket"}
            if len(history) > 2000:
                for old in sorted(history)[:-2000]:
                    history.pop(old, None)

    def send_candles(self, rows: list[dict[str, Any]], force: bool = False) -> None:
        if not rows:
            return
        self.remember_closed(rows)
        boundary = int(time.time() // PERIOD) * PERIOD
        rows = [
            r for r in rows
            if int(float(r["timestamp"]) // PERIOD) * PERIOD < boundary
            and (r.get("asset") in OTC_PAIRS or r.get("asset") == REAL_ASSET)
        ]
        if not rows:
            return
        signature = "|".join(f"{r['asset']}:{r['timestamp']}:{r['close']}" for r in rows[-10:])
        if not force and signature == self.last_signature and time.monotonic() - self.last_send < 45:
            return

        otc = [r for r in rows if r.get("asset") in OTC_PAIRS]
        real = [r for r in rows if r.get("asset") == REAL_ASSET]
        accepted = 0
        if otc:
            try:
                data = self.post("/quotex/ingest", {
                    "sent_at": time.time(), "active_asset": otc[-1]["asset"], "candles": otc,
                })
                accepted += int(data.get("accepted", 0) or 0)
            except Exception as exc:
                log(f"OTC candle upload failed: {exc}")
        if real:
            try:
                data = self.post("/quotex/real-ingest", {
                    "sent_at": time.time(), "candles": real,
                })
                accepted += int(data.get("accepted", 0) or 0)
            except Exception as exc:
                log(f"real-market candle upload failed: {exc}")
        self.last_signature = signature
        self.last_send = time.monotonic()
        log(f"sent {accepted} closed candle rows ({len(otc)} OTC, {len(real)} real {REAL_ASSET})")

    def send_tick(self, asset: str, price: float, ts: float) -> None:
        if asset not in OTC_PAIRS and asset != REAL_ASSET:
            return
        now = time.monotonic()
        if now - self.last_quote_send.get(asset, 0.0) < 1.0:
            return
        endpoint = "/quotex/tick-ingest" if asset in OTC_PAIRS else "/quotex/real-ingest"
        payload = (
            {"sent_at": time.time(), "asset": asset, "ticks": [{"price": price, "timestamp": ts}]}
            if asset in OTC_PAIRS else
            {"sent_at": time.time(), "quotes": [{"asset": asset, "price": price, "timestamp": ts}]}
        )
        try:
            self.post(endpoint, payload)
            self.last_quote_send[asset] = now
        except Exception as exc:
            log(f"{asset} tick upload failed: {exc}")

        bucket = int(ts // PERIOD) * PERIOD
        state = self.partial.get(asset)
        if not state or state["bucket"] != bucket:
            if state:
                self.send_candles([{k: v for k, v in state.items() if k != "bucket"}], force=True)
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

    def flush_partials(self) -> None:
        boundary = int(time.time() // PERIOD) * PERIOD
        for asset, state in list(self.partial.items()):
            bucket = int(state.get("bucket", 0))
            if bucket + PERIOD > boundary:
                continue
            if self.last_partial_flush_bucket.get(asset) == bucket:
                continue
            self.send_candles([{k: v for k, v in state.items() if k != "bucket"}], force=True)
            self.last_partial_flush_bucket[asset] = bucket


async def run() -> None:
    if not INGEST_SECRET:
        raise RuntimeError("Set QUOTEX_INGEST_SECRET")
    start_health_server()
    storage = None
    if STORAGE_STATE_B64:
        try:
            storage = json.loads(base64.b64decode(STORAGE_STATE_B64).decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Invalid QUOTEX_STORAGE_STATE_B64: {exc}") from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = await browser.new_context(storage_state=storage)
        page = await context.new_page()
        collector = Collector()
        sockets: list[Any] = []

        async def handle_frame(payload: str) -> None:
            try:
                event, data = decode_socket_message(payload)
                if event == "quotes/stream":
                    rows = data if isinstance(data, list) else [data]
                    for row in rows:
                        asset, price, ts = price_from_payload(row)
                        if asset and price is not None:
                            collector.send_tick(asset, price, ts)
                elif event in {
                    "candle", "candles", "history/list", "history/list/v2",
                    "history/load", "chart_notification/get",
                }:
                    rows = normalise_candles(data)
                    if rows:
                        collector.send_candles(rows)
                else:
                    asset, price, ts = price_from_payload(data)
                    if asset and price is not None:
                        collector.send_tick(asset, price, ts)
            except Exception as exc:
                log(f"frame handling error: {exc}")

        async def on_websocket(ws) -> None:
            url = ws.url
            sockets.append(ws)
            log(f"captured browser WebSocket: {url.split('?')[0]}")
            ws.on("framereceived", handle_frame)

            async def on_close() -> None:
                log(f"browser WebSocket closed: {url.split('?')[0]}")
            ws.on("close", on_close)

            # Ask the active Quotex socket for recent OTC history. This uses
            # the same history request shape as the working local collector.
            assets = sorted(OTC_PAIRS)
            now = int(time.time())
            try:
                for i, asset in enumerate(assets):
                    for window in range(2):
                        request = ["history/load", {
                            "asset": asset,
                            "index": i * 2 + window,
                            "time": now - window * 3600,
                            "offset": 3600,
                            "period": PERIOD,
                        }]
                        await ws.send("42" + json.dumps(request, separators=(",", ":")))
                        await asyncio.sleep(0.03)
            except Exception as exc:
                log(f"OTC history request failed: {exc}")

        page.on("websocket", on_websocket)
        log(f"opening {QUOTEX_URL}; OTC pairs={len(OTC_PAIRS)}, real asset={REAL_ASSET}")
        await page.goto(QUOTEX_URL, wait_until="domcontentloaded", timeout=60000)
        log(f"page loaded: title={await page.title()!r} url={page.url}")
        await page.wait_for_timeout(10000)
        log(f"WebSockets observed after initial load: {len(sockets)}")

        # Login is optional when a storage state is supplied. Credential
        # fields are kept as environment variables and never logged.
        if LOGIN_EMAIL and LOGIN_PASSWORD:
            email = page.locator('input[type="email"], input[name="email"], input[placeholder*="mail" i]').first
            password = page.locator('input[type="password"], input[name="password"]').first
            if await email.count() and await password.count():
                await email.fill(LOGIN_EMAIL)
                await password.fill(LOGIN_PASSWORD)
                button = page.locator(
                    'button[type="submit"], button:has-text("Sign in"), '
                    'button:has-text("Login"), button:has-text("Log in")'
                ).first
                if await button.count():
                    await button.click()
                    await page.wait_for_timeout(8000)

        await page.reload(wait_until="domcontentloaded", timeout=60000)
        log(f"page reloaded: title={await page.title()!r} url={page.url}; WebSockets={len(sockets)}")
        log("cloud browser running: collecting both OTC and real-market WebSocket data")

        diagnostic_at = 0.0
        while True:
            await page.wait_for_timeout(5000)
            collector.flush_partials()
            if time.monotonic() - diagnostic_at >= 60:
                diagnostic_at = time.monotonic()
                log(f"collector diagnostic: websockets={len(sockets)} partials={len(collector.partial)} closed_assets={len(collector.closed_history)}")
            if page.is_closed():
                raise RuntimeError("Quotex page closed")
            try:
                await page.title()
            except Exception as exc:
                raise RuntimeError(f"Quotex page unavailable: {exc}") from exc


if __name__ == "__main__":
    asyncio.run(run())
