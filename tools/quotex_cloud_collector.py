"""Cloud Quotex Real-Market collector.

Runs a headless Chromium session in a Render background worker and forwards
Quotex WebSocket market data to the existing authenticated real-market ingest.

OTC is deliberately not handled here.

Authentication options:
  1) QUOTEX_STORAGE_STATE_B64: base64-encoded Playwright storage_state JSON.
  2) QUOTEX_LOGIN_EMAIL + QUOTEX_LOGIN_PASSWORD: best-effort login fallback.

The storage-state route is preferred because it avoids hard-coding account
credentials in the collector and can preserve an already-authenticated session.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Any

import requests
from playwright.async_api import async_playwright

BOT_URL = os.getenv("MMC_BOT_URL", "https://mmc-treading-bot.onrender.com").rstrip("/")
INGEST_SECRET = os.getenv("QUOTEX_INGEST_SECRET", "").strip()
QUOTEX_URL = os.getenv("QUOTEX_URL", "https://market-qx.info/en/demo-trade")
STORAGE_STATE_B64 = os.getenv("QUOTEX_STORAGE_STATE_B64", "").strip()
LOGIN_EMAIL = os.getenv("QUOTEX_LOGIN_EMAIL", "").strip()
LOGIN_PASSWORD = os.getenv("QUOTEX_LOGIN_PASSWORD", "").strip()
ASSET = os.getenv("QUOTEX_REAL_ASSET", "AUDCAD").strip().upper()
PERIOD = 60


def log(message: str) -> None:
    print(f"[MMC Quotex Cloud Collector] {message}", flush=True)


def decode_json_after_prefix(text: str) -> Any:
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
        packet = decode_json_after_prefix(payload[2:])
        if isinstance(packet, list) and packet:
            return str(packet[0]), packet[1] if len(packet) > 1 else None
    if payload.startswith("45") and "_placeholder" in payload:
        packet = decode_json_after_prefix(payload[4:])
        if isinstance(packet, list) and packet:
            return str(packet[0]), packet[1] if len(packet) > 1 else None
    packet = decode_json_after_prefix(payload)
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


def candle_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        asset = payload.get("asset") or payload.get("symbol") or ASSET
        items = payload.get("candles") or payload.get("data") or []
        if all(k in payload for k in ("open", "high", "low", "close")):
            items = [payload]
    elif isinstance(payload, list):
        asset, items = ASSET, payload
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


class Ingest:
    def __init__(self) -> None:
        self.http = requests.Session()
        self.last_quote = 0.0
        self.partial: dict[str, dict[str, Any]] = {}
        self.last_candle = 0.0

    def post(self, payload: dict[str, Any]) -> None:
        if not INGEST_SECRET:
            raise RuntimeError("QUOTEX_INGEST_SECRET is missing")
        response = self.http.post(
            f"{BOT_URL}/quotex/real-ingest",
            json=payload,
            headers={"X-MMC-Quotex-Key": INGEST_SECRET},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "real-ingest rejected data"))

    def quote(self, asset: str, price: float, ts: float) -> None:
        if asset != ASSET or time.monotonic() - self.last_quote < 1.0:
            return
        self.post({"sent_at": time.time(), "quotes": [{"asset": asset, "price": price, "timestamp": ts}]})
        self.last_quote = time.monotonic()

    def tick(self, asset: str, price: float, ts: float) -> None:
        if asset != ASSET:
            return
        self.quote(asset, price, ts)
        bucket = int(ts // PERIOD) * PERIOD
        state = self.partial.get(asset)
        if not state or state["bucket"] != bucket:
            if state:
                self.post({"sent_at": time.time(), "candles": [{k: v for k, v in state.items() if k != "bucket"}]})
            state = {"bucket": bucket, "asset": asset, "period": PERIOD, "timestamp": float(bucket),
                     "open": price, "high": price, "low": price, "close": price}
            self.partial[asset] = state
        else:
            state["high"] = max(state["high"], price)
            state["low"] = min(state["low"], price)
            state["close"] = price
        if time.monotonic() - self.last_candle >= 10:
            self.post({"sent_at": time.time(), "candles": [{k: v for k, v in state.items() if k != "bucket"}]})
            self.last_candle = time.monotonic()

    def rows(self, rows: list[dict[str, Any]]) -> None:
        rows = [r for r in rows if r.get("asset") == ASSET]
        if rows:
            self.post({"sent_at": time.time(), "candles": rows})


async def login_if_needed(page) -> None:
    if not LOGIN_EMAIL or not LOGIN_PASSWORD:
        return
    # Only attempt login when the current page looks like a login page.
    email = page.locator('input[type="email"], input[name="email"], input[placeholder*="mail" i]').first
    password = page.locator('input[type="password"], input[name="password"]').first
    if await email.count() == 0 or await password.count() == 0:
        return
    log("login form detected; attempting credential login")
    await email.fill(LOGIN_EMAIL)
    await password.fill(LOGIN_PASSWORD)
    buttons = page.locator('button[type="submit"], button:has-text("Sign in"), button:has-text("Login"), button:has-text("Log in")')
    if await buttons.count():
        await buttons.first.click()
    await page.wait_for_timeout(8000)


async def run() -> None:
    if not INGEST_SECRET:
        raise RuntimeError("Set QUOTEX_INGEST_SECRET")
    ingest = Ingest()
    storage = None
    if STORAGE_STATE_B64:
        try:
            storage = json.loads(base64.b64decode(STORAGE_STATE_B64).decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Invalid QUOTEX_STORAGE_STATE_B64: {exc}") from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(storage_state=storage)
        page = await context.new_page()

        async def on_websocket(ws) -> None:
            url = ws.url.lower()
            if "socket.io" not in url and "market-qx" not in url and "qxbroker" not in url:
                return
            log(f"captured Quotex WebSocket: {url.split('?')[0]}")

            async def handle_frame(payload: str) -> None:
                try:
                    event, data = decode_socket_message(payload)
                    if event == "quotes/stream":
                        rows = data if isinstance(data, list) else [data]
                        for row in rows:
                            asset, price, ts = price_from_payload(row)
                            if asset and price is not None:
                                ingest.tick(asset, price, ts)
                    elif event in {"candle", "candles", "history/list", "history/list/v2", "chart_notification/get"}:
                        ingest.rows(candle_rows(data))
                    else:
                        asset, price, ts = price_from_payload(data)
                        if asset and price is not None:
                            ingest.tick(asset, price, ts)
                except Exception as exc:
                    log(f"frame handling error: {exc}")

            ws.on("framereceived", handle_frame)

        page.on("websocket", on_websocket)
        log(f"opening {QUOTEX_URL} for {ASSET}")
        await page.goto(QUOTEX_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        await login_if_needed(page)
        await page.reload(wait_until="domcontentloaded", timeout=60000)
        log("cloud browser is running; waiting for Quotex WebSocket data")

        while True:
            await page.wait_for_timeout(15000)
            # Keep the session alive. If the page becomes unusable, the process
            # exits so Render can restart the worker.
            if page.is_closed():
                raise RuntimeError("Quotex page closed")
            try:
                await page.title()
            except Exception as exc:
                raise RuntimeError(f"Quotex page became unavailable: {exc}") from exc


if __name__ == "__main__":
    asyncio.run(run())
