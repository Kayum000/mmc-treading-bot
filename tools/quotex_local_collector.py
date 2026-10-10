"""Local laptop collector for a user-opened Quotex browser tab.

Signal-data-only: it does not log in, collect passwords/SSIDs, or place orders.
It attaches to Chrome DevTools Protocol (CDP), reads the browser's WebSocket
frames, normalizes Quotex candles/quotes, builds 1-minute OHLC when needed,
and sends OTC candles to the existing OTC ingest plus real-market quotes and
candles to the separate Quotex real-market feed.

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
import queue
import re
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests
import websockets

from data.otc_markets import OTC_PAIRS, normalize_detected_market

# Quotex Real-Market symbols use the compact instrument IDs (EURUSD, GBPUSD,
# ...), while the dashboard displays them as EUR/USD, GBP/USD, etc. Keep this
# list local to the PC collector so the existing bot/server code stays untouched.
REAL_MARKET_PAIRS = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD",
    "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "EURCHF", "GBPCHF",
    "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY", "EURAUD", "GBPAUD",
    "AUDCAD", "NZDCAD",
)

PERIOD = 60
CDP_URL = os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9222").rstrip("/")
BOT_URL = os.getenv("MMC_BOT_URL", "https://mmc-treading-bot.onrender.com").rstrip("/")
INGEST_SECRET = os.getenv("QUOTEX_INGEST_SECRET", "").strip()
VERBOSE = os.getenv("QUOTEX_DEBUG_VERBOSE", "0").strip() == "1"
STATUS_PATH = os.path.join(os.path.dirname(__file__), "collector_status.json")


def log(message: str) -> None:
    line = f"[MMC Quotex Laptop Collector] {message}"
    print(line, flush=True)
    try:
        with open(os.path.join(os.path.dirname(__file__), "collector_runtime.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def _target() -> dict[str, Any]:
    response = requests.get(f"{CDP_URL}/json/list", timeout=5)
    response.raise_for_status()
    targets = response.json()
    allowed_hosts = ("qxbroker.com", "market-qx.trade", "market-qx.info")
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
            "and leave the market chart open."
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
        if "[" in payload or "{" in payload:
            decoded = payload
        else:
            raw = base64.b64decode(payload)
            decoded = raw.decode("utf-8", errors="ignore")
        data = _json_after_prefix(decoded)
        if isinstance(data, list) and data and isinstance(data[0], (int, float)):
            if len(data) >= 3:
                return None, data[2]
            if len(data) == 2:
                return None, data[1]
        if isinstance(data, list) and data and isinstance(data[0], list):
            return "quotes/stream", data
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
            if not item_asset or None in (ts, op, hi, lo, cl):
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


def _normalise_history(payload: Any, fallback_asset: str | None = None) -> list[dict[str, Any]]:
    """Normalize either real OHLC candle rows or timestamp/price history points.

    Quotex history/list/v2 can include a `candles` array of OHLC tuples and a
    separate `history` price series. Prefer the actual candles when present;
    aggregating the second field of OHLC tuples as if it were a quote loses the
    original high/low/close and can shrink history to only a few bars.
    """
    if not isinstance(payload, dict):
        return []

    rows = _normalise_candle(payload, fallback_asset=fallback_asset)
    if rows:
        boundary = int(time.time() // PERIOD) * PERIOD
        return [
            row for row in rows
            if int(float(row["timestamp"]) // PERIOD) * PERIOD < boundary
        ]

    asset = payload.get("asset") or payload.get("symbol") or fallback_asset
    history = payload.get("history")
    if history is None:
        history = payload.get("data") or payload.get("candles") or []
    if isinstance(history, dict):
        history = list(history.values())
    if not asset or not isinstance(history, list):
        return []

    buckets: dict[int, dict[str, Any]] = {}
    for item in history:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            ts, price = float(item[0]), float(item[1])
            if ts > 10_000_000_000:
                ts /= 1000.0
        except (TypeError, ValueError, OverflowError):
            continue
        bucket = int(ts // PERIOD) * PERIOD
        state = buckets.get(bucket)
        if state is None:
            buckets[bucket] = {
                "bucket": bucket, "asset": str(asset), "period": PERIOD,
                "timestamp": float(bucket), "open": price, "high": price,
                "low": price, "close": price,
            }
        else:
            state["high"] = max(state["high"], price)
            state["low"] = min(state["low"], price)
            state["close"] = price
    boundary = int(time.time() // PERIOD) * PERIOD
    return [v for k, v in sorted(buckets.items()) if k < boundary]


def _price_from_payload(payload: Any) -> tuple[str | None, float | None, float | None]:
    if isinstance(payload, dict):
        asset = payload.get("asset") or payload.get("symbol")
        value = payload.get("price", payload.get("close"))
        ts = payload.get("timestamp", payload.get("time"))
        try:
            return str(asset) if asset else None, float(value), float(ts) if ts is not None else time.time()
        except (TypeError, ValueError):
            return None, None, None
    if isinstance(payload, list) and len(payload) >= 3 and isinstance(payload[0], str):
        try:
            return str(payload[0]), float(payload[2]), float(payload[1])
        except (TypeError, ValueError):
            return None, None, None
    return None, None, None


class Collector:
    def __init__(self, selected_asset: str, history_asset_by_index: dict[int, str] | None = None) -> None:
        self.selected_asset = selected_asset
        # Quotex history responses may omit the asset name but echo the request
        # index. Keep the correlation map so delayed responses cannot be
        # assigned to a different market after a market switch.
        self.history_asset_by_index = dict(history_asset_by_index or {})
        self.partial: dict[str, dict[str, Any]] = {}
        # Keep a rolling closed-candle history locally so every ingest can
        # refresh Render with enough historical bars.
        self.closed_history: dict[str, dict[int, dict[str, Any]]] = {}
        self.session = requests.Session()
        self.last_signature = ""
        self.last_send = 0.0
        self.last_partial_send: dict[str, float] = {}
        self.last_quote_send: dict[str, float] = {}
        self.last_data_at = time.monotonic()
        self.last_market_data_at = time.monotonic()
        self.last_status_write = 0.0
        self.last_status_asset = ""
        self.last_status_type = ""
        self.last_real_data_at = 0.0
        self.last_otc_data_at = 0.0
        self._write_status("running", "starting", "")
        # Network uploads never run on the CDP/WebSocket event loop. A bounded
        # queue keeps short Render latency spikes from blocking market capture
        # while also preventing an outage from growing memory without limit.
        self._candle_queue: queue.Queue[list[dict[str, Any]]] = queue.Queue(maxsize=50)
        self._quote_queue: queue.Queue[tuple[str, str, dict[str, Any]]] = queue.Queue(maxsize=250)
        self._upload_stop = threading.Event()
        self._upload_thread = threading.Thread(
            target=self._upload_worker,
            name="mmc-quotex-upload-worker",
            daemon=True,
        )
        self._upload_thread.start()
        log("non-blocking upload worker started (bounded candle=50, quote=250)")

    def _write_status(self, state: str, data_type: str, asset: str) -> None:
        now = time.time()
        if state == "running" and data_type != "starting" and now - self.last_status_write < 5:
            return
        payload = {
            "process_alive": True,
            "state": state,
            "last_data_at": now if data_type != "starting" else None,
            "last_data_type": data_type,
            "last_asset": asset,
            "last_real_data_at": self.last_real_data_at or None,
            "last_otc_data_at": self.last_otc_data_at or None,
            "updated_at": now,
        }
        tmp = f"{STATUS_PATH}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, separators=(",", ":"))
            # Windows may briefly deny replacement while another process scans
            # the destination. Use a writer-specific temp file and retry only
            # transient permission/sharing errors before reporting failure.
            for attempt in range(5):
                try:
                    os.replace(tmp, STATUS_PATH)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (2 ** attempt))
            self.last_status_write = now
            self.last_status_asset = asset
            self.last_status_type = data_type
        except OSError as exc:
            log(f"status file update failed after retry: {exc}")
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    def set_selected_asset(self, asset: str) -> None:
        self.selected_asset = str(asset or "").strip()
        self.partial.clear()
        self.closed_history.clear()
        self.last_signature = ""
        self.last_send = 0.0
        self._write_status("live", "market changed", self.selected_asset)
        log(f"selected market: {self.selected_asset}")

    def _is_selected(self, asset: str) -> bool:
        return bool(self.selected_asset) and str(asset or "").strip().lower() == self.selected_asset.lower()

    def _mark_data(self, asset: str, data_type: str) -> None:
        if not self._is_selected(asset):
            return
        self.last_data_at = time.monotonic()
        self.last_market_data_at = self.last_data_at
        now = time.time()
        if asset in OTC_PAIRS:
            self.last_otc_data_at = now
        else:
            self.last_real_data_at = now
        self._write_status("live", data_type, asset)

    def _upload_worker(self) -> None:
        while not self._upload_stop.is_set():
            try:
                rows = self._candle_queue.get(timeout=0.2)
            except queue.Empty:
                try:
                    kind, endpoint, payload = self._quote_queue.get_nowait()
                except queue.Empty:
                    continue
                try:
                    result = self._post(endpoint, payload)
                    log(f"queued {kind} upload accepted={result.get('accepted', '?')}")
                except Exception as exc:
                    log(f"queued {kind} upload failed; stream stays alive: {exc}")
                finally:
                    self._quote_queue.task_done()
                continue
            try:
                self._send_now(rows)
            except Exception as exc:
                log(f"queued candle upload failed; stream stays alive: {exc}")
            finally:
                self._candle_queue.task_done()

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not INGEST_SECRET:
            raise RuntimeError("QUOTEX_INGEST_SECRET is missing. Set the same secret on Render and locally.")
        response = self.session.post(
            f"{BOT_URL}{endpoint}",
            json=payload,
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
            raise RuntimeError(f"Render rejected market data: {data.get('error', 'unknown error')}")
        return data

    def _remember_closed(self, rows: list[dict[str, Any]]) -> None:
        boundary = int(time.time() // PERIOD) * PERIOD
        for row in rows:
            try:
                asset = str(row.get("asset") or "")
                ts = float(row["timestamp"])
                bucket = int(ts // PERIOD) * PERIOD
            except (TypeError, ValueError, KeyError):
                continue
            if not asset or bucket >= boundary:
                continue
            history = self.closed_history.setdefault(asset, {})
            history[bucket] = {k: v for k, v in row.items() if k != "bucket"}
            # Signal generation needs 80 closed candles. Keep a larger local
            # safety window, but do not rebuild/upload thousands of bars on
            # every refresh; that only adds Render latency and bandwidth.
            if len(history) > 300:
                for old_bucket in sorted(history)[:-300]:
                    history.pop(old_bucket, None)

    def _send(self, rows: list[dict[str, Any]]) -> None:
        rows = [r for r in rows if self._is_selected(str(r.get("asset") or ""))]
        if not rows:
            return
        try:
            self._candle_queue.put_nowait(rows)
        except queue.Full:
            log("candle upload queue full; preserving WebSocket stream and dropping queued refresh")

    def _send_now(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        self._remember_closed(rows)
        expanded: list[dict[str, Any]] = []
        for asset in sorted({str(r.get("asset") or "") for r in rows if r.get("asset")}):
            history = self.closed_history.get(asset, {})
            # 120 closed candles covers the 80-candle signal window plus a
            # healthy safety margin while keeping each refresh small.
            expanded.extend(list(history.values())[-120:])
        rows = expanded or rows
        otc_rows = [r for r in rows if r.get("asset") in OTC_PAIRS]
        real_rows = [r for r in rows if r.get("asset") not in OTC_PAIRS]
        signature = "|".join(f"{r['asset']}:{r['timestamp']}:{r['close']}" for r in rows[-5:])
        if signature == self.last_signature and time.monotonic() - self.last_send < 45:
            return
        accepted = 0
        if otc_rows:
            try:
                data = self._post("/quotex/ingest", {"sent_at": time.time(), "active_asset": otc_rows[-1].get("asset"), "candles": otc_rows})
            except Exception as exc:
                log(f"candle upload failed; keeping Quotex stream open: {exc}")
                return
            accepted += int(data.get("accepted", 0) or 0)
        if real_rows:
            try:
                data = self._post("/quotex/real-ingest", {"sent_at": time.time(), "candles": real_rows})
            except Exception as exc:
                log(f"real-market candle upload failed; keeping Quotex stream open: {exc}")
                return
            accepted += int(data.get("accepted", 0) or 0)
        self.last_signature = signature
        self.last_send = time.monotonic()
        log(f"sent {accepted} closed candle rows to MMC ({len(otc_rows)} OTC, {len(real_rows)} real-market)")

    def _send_quote(self, asset: str, price: float, ts: float) -> None:
        if not self._is_selected(asset):
            return
        now = time.monotonic()
        if now - self.last_quote_send.get(asset, 0.0) < 1.0:
            return
        endpoint = "/quotex/tick-ingest" if asset in OTC_PAIRS else "/quotex/real-ingest"
        payload = (
            {"sent_at": time.time(), "asset": asset, "ticks": [{"price": price, "timestamp": ts}]}
            if asset in OTC_PAIRS
            else {"sent_at": time.time(), "quotes": [{"asset": asset, "price": price, "timestamp": ts}]}
        )
        try:
            self._quote_queue.put_nowait(("OTC tick" if asset in OTC_PAIRS else "real quote", endpoint, payload))
            self.last_quote_send[asset] = now
        except queue.Full:
            # Quotes are disposable between ticks; candles remain in their
            # separate queue so a temporary Render outage cannot starve them.
            log(f"quote upload queue full; dropping transient quote for {asset}")
        return

    def _add_price(self, asset: str, price: float, ts: float) -> None:
        if not asset:
            return
        self._mark_data(asset, "tick")
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

    def flush_partials(self) -> None:
        now = time.monotonic()
        for asset, state in list(self.partial.items()):
            if now - self.last_partial_send.get(asset, 0.0) < 10:
                continue
            row = {k: v for k, v in state.items() if k != "bucket"}
            self._send([row])
            self.last_partial_send[asset] = now

    def handle(self, event_name: str | None, payload: Any) -> None:
        if not event_name:
            return
        name = event_name.lower()
        if VERBOSE:
            log(f"event: {event_name}")
        if name == "history/list/v2":
            fallback_asset = None
            if isinstance(payload, dict):
                try:
                    fallback_asset = self.history_asset_by_index.get(int(payload.get("index")))
                except (TypeError, ValueError):
                    fallback_asset = None
                if not fallback_asset and not (payload.get("asset") or payload.get("symbol")):
                    fallback_asset = self.selected_asset
            rows = _normalise_history(payload, fallback_asset=fallback_asset)
            rows = [r for r in rows if self._is_selected(str(r.get("asset") or ""))]
            if rows:
                rows = sorted(rows, key=lambda r: float(r.get("timestamp", 0)))
                first_ts = datetime.fromtimestamp(float(rows[0]["timestamp"]), tz=timezone.utc).isoformat(timespec="minutes")
                last_ts = datetime.fromtimestamp(float(rows[-1]["timestamp"]), tz=timezone.utc).isoformat(timespec="minutes")
                log(f"history/list/v2 parsed {len(rows)} selected closed candles ({first_ts} to {last_ts})")
                self._mark_data(self.selected_asset, "closed candle")
                self._send(rows)
            else:
                asset_hint = payload.get("asset") or payload.get("symbol") if isinstance(payload, dict) else None
                log(f"selected market history contained no usable OHLC/tick rows (asset={asset_hint or self.selected_asset})")
            return
        if name in {"candle", "candles", "history/list", "history/load", "chart_notification/get"}:
            fallback_asset = None
            if isinstance(payload, dict):
                try:
                    fallback_asset = self.history_asset_by_index.get(int(payload.get("index")))
                except (TypeError, ValueError):
                    fallback_asset = None
                if not fallback_asset and not (payload.get("asset") or payload.get("symbol")):
                    fallback_asset = self.selected_asset
            rows = _normalise_candle(payload, fallback_asset=fallback_asset)
            if not rows and name in {"history/list", "history/load"}:
                rows = _normalise_history(payload, fallback_asset=fallback_asset)
            rows = [r for r in rows if self._is_selected(str(r.get("asset") or ""))]
            if rows:
                rows = sorted(rows, key=lambda r: float(r.get("timestamp", 0)))
                if name in {"history/list", "history/load"}:
                    first_ts = datetime.fromtimestamp(float(rows[0]["timestamp"]), tz=timezone.utc).isoformat(timespec="minutes")
                    last_ts = datetime.fromtimestamp(float(rows[-1]["timestamp"]), tz=timezone.utc).isoformat(timespec="minutes")
                    log(f"{name} parsed {len(rows)} selected closed candles ({first_ts} to {last_ts})")
                self._mark_data(self.selected_asset, "candle")
                self._send(rows)
            return
        if name == "quotes/stream":
            # This is the live quote path. Ignoring it made the collector
            # repeatedly reconnect after receiving history but no candle/tick
            # events. Accept the common flat and nested Socket.IO row shapes.
            pending = list(payload) if isinstance(payload, list) else [payload]
            while pending:
                item = pending.pop(0)
                if isinstance(item, list) and item and isinstance(item[0], (list, tuple, dict)):
                    pending[0:0] = item
                    continue
                asset, price, ts = _price_from_payload(item)
                if not asset or price is None or not self._is_selected(asset):
                    continue
                if ts is None:
                    ts = time.time()
                if ts > 10_000_000_000:
                    ts /= 1000
                self._add_price(asset, price, ts)
                self._send_quote(asset, price, ts)
            return
        if name in {"candle-generated", "quote", "quotes", "price", "tick", "instrument/price"}:
            rows = [r for r in _normalise_candle(payload) if self._is_selected(str(r.get("asset") or ""))]
            if rows:
                assets = sorted({str(r.get("asset") or "") for r in rows if r.get("asset")})
                self._mark_data(assets[-1] if assets else "", "candle")
                self._send(rows)
                return
            return


def _selected_asset_from_text(text: str) -> str | None:
    match = re.search(r"([A-Z]{3}\s*/\s*[A-Z]{3}(?:\s*\(OTC\))?)", str(text or "").upper())
    if not match:
        return None
    visible = match.group(1)
    otc = normalize_detected_market(visible)
    if otc:
        return otc
    compact = re.sub(r"[^A-Z]", "", visible)
    return compact if compact in REAL_MARKET_PAIRS else None


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
        await _cdp_command(ws, counter, "Page.enable")
        bridge = """(() => { if (window.__mmcHistoryBridgeInstalled) return; window.__mmcHistoryBridgeInstalled=true; window.__mmcSockets=[]; const O=window.WebSocket; const W=function(...a){const s=new O(...a); window.__mmcSockets.push(s); return s;}; W.prototype=O.prototype; window.WebSocket=W; })();"""
        await _cdp_command(ws, counter, "Page.addScriptToEvaluateOnNewDocument", {"source": bridge})
        await _cdp_command(ws, counter, "Page.reload", {"ignoreCache": False})
        log("CDP Network capture enabled and Quotex page reloaded once to capture WebSocket from startup.")
        # Give Quotex enough time to create the browser WebSocket before the
        # history backfill is sent; otherwise the socket list can still be empty.
        await asyncio.sleep(6)
        selected_probe = await _cdp_command(ws, counter, "Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
        selected_text = selected_probe.get("result", {}).get("result", {}).get("value", "")
        selected_asset = _selected_asset_from_text(selected_text)
        if not selected_asset:
            raise RuntimeError("Could not detect the currently selected Quotex market from the chart.")

        collector = Collector(selected_asset)
        log(f"selected market: {selected_asset} | ONLY this market will be sent")

        async def request_selected_history(asset: str) -> None:
            # Send subscriptions and backfill for ONLY the browser's current
            # market. The old all-pairs request flood could delay or lose the
            # selected pair's history responses.
            now = int(time.time())
            base = int(time.time() * 1000)
            while any((base + w) in collector.history_asset_by_index for w in range(4)):
                base += 10
            requests_for_history = [
                {"index": base + w, "time": now - w * 3600, "delay_ms": w * 350}
                for w in range(4)
            ]
            collector.history_asset_by_index.update(
                {int(item["index"]): asset for item in requests_for_history}
            )
            asset_json = json.dumps(asset)
            requests_json = json.dumps(requests_for_history, separators=(",", ":"))
            request_js = """(() => {
              const asset=__ASSET__;
              const pages=__PAGES__;
              const sockets=(window.__mmcSockets||[]).filter(x=>x&&x.readyState===1);
              const send=(x,packet)=>{try{x.send(packet)}catch(_){}};
              for(const x of sockets){
                send(x,'42["instruments/update",'+JSON.stringify({asset:asset,period:60})+']');
                send(x,'42["depth/follow",'+JSON.stringify(asset)+']');
                send(x,'42["chart_notification/get",'+JSON.stringify({asset:asset,version:"1.0.0"})+']');
              }
              const hist=p=>'42["history/load",'+JSON.stringify({asset:asset,index:p.index,time:p.time,offset:3600,period:60})+']';
              for(const page of pages) for(const x of sockets) setTimeout(()=>send(x,hist(page)),page.delay_ms);
              return {sockets:sockets.length,selected_asset:asset,history_requests:pages.length};
            })()""".replace("__ASSET__", asset_json).replace("__PAGES__", requests_json)
            result = await _cdp_command(ws, counter, "Runtime.evaluate", {"expression": request_js, "returnByValue": True})
            value = result.get("result", {}).get("result", {}).get("value", {})
            log(f"Requested selected-market history only: {value}")
            if not value.get("sockets"):
                log("No ready Quotex WebSocket yet; selected-market history will be retried after reconnect.")

        await request_selected_history(selected_asset)
        pending_event: str | None = None
        last_frame_at = time.monotonic()
        last_selection_check = 0.0
        while True:
            now_mono = time.monotonic()
            if now_mono - last_selection_check >= 2.0:
                last_selection_check = now_mono
                probe = await _cdp_command(ws, counter, "Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
                visible = probe.get("result", {}).get("result", {}).get("value", "")
                new_asset = _selected_asset_from_text(visible)
                if new_asset and new_asset != collector.selected_asset:
                    collector.set_selected_asset(new_asset)
                    log(f"market selection changed -> {new_asset}; old market data is discarded")
                    await request_selected_history(new_asset)
            try:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except asyncio.TimeoutError:
                collector.flush_partials()
                if time.monotonic() - last_frame_at >= 30:
                    log("No Quotex WebSocket frames for 30s; reloading the page to recover the stream.")
                    await _cdp_command(ws, counter, "Page.reload", {"ignoreCache": False})
                    # Wait for the page-created WebSocket to be captured by
                    # the CDP bridge, then re-subscribe/backfill only the
                    # currently selected market. A reload alone is not enough
                    # to restore our explicit history requests.
                    await asyncio.sleep(6)
                    probe = await _cdp_command(ws, counter, "Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
                    visible = probe.get("result", {}).get("result", {}).get("value", "")
                    reloaded_asset = _selected_asset_from_text(visible)
                    if reloaded_asset and reloaded_asset != collector.selected_asset:
                        collector.set_selected_asset(reloaded_asset)
                        log(f"market selection after recovery reload -> {reloaded_asset}")
                    await request_selected_history(collector.selected_asset)
                    last_frame_at = time.monotonic()
                continue
            if message.get("method") != "Network.webSocketFrameReceived":
                continue
            last_frame_at = time.monotonic()
            response = message.get("params", {}).get("response", {})
            payload = response.get("payloadData", "")
            opcode = int(response.get("opcode", 1))
            event_name, data = _decode_socket_message(payload, opcode)
            if opcode != 1 and pending_event and data is not None:
                if event_name is None:
                    event_name = pending_event
                pending_event = None
            if event_name and isinstance(data, dict) and data.get("_placeholder"):
                pending_event = event_name
                continue
            collector.handle(event_name, data)
            if time.monotonic() - collector.last_market_data_at >= 60:
                raise RuntimeError("No usable Quotex market data for 60s; reconnecting to the chart.")


def main() -> int:
    try:
        while True:
            try:
                asyncio.run(run())
            except KeyboardInterrupt:
                log("stopped")
                return 0
            except Exception as exc:
                log(f"stream error: {exc}; reconnecting in 3s")
                time.sleep(3)
    except KeyboardInterrupt:
        log("stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
