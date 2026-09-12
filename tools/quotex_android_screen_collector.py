"""Local Android Quotex screen collector.

This collector reads the user's own Android Quotex display through ADB
screenshots. It does not log in, read passwords/SSIDs, inspect network
credentials, or place trades. It detects the red/green 1-minute candles in
the chart area and converts their screen geometry into direction-preserving
OHLC-like candles for the existing MMC OTC pressure strategy.

The collector is intentionally conservative: the newest visible candle is
excluded because it is normally still forming. If the chart cannot be read
confidently, no candle data is sent.

Environment variables:
  MMC_BOT_URL            default https://mmc-treading-bot.onrender.com
  QUOTEX_INGEST_SECRET   same secret configured on Render
  QUOTEX_ANDROID_ASSET   default USDARS_otc
  QUOTEX_SCREEN_FPS      default 2 screenshots/sec
  QUOTEX_DEBUG_VERBOSE   1 for local detection diagnostics
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

import cv2
import numpy as np
import requests

PERIOD = 60
BOT_URL = os.getenv("MMC_BOT_URL", "https://mmc-treading-bot.onrender.com").rstrip("/")
INGEST_SECRET = os.getenv("QUOTEX_INGEST_SECRET", "").strip()
ASSET = os.getenv("QUOTEX_ANDROID_ASSET", "USDARS_otc").strip()
FPS = max(1.0, min(float(os.getenv("QUOTEX_SCREEN_FPS", "2")), 4.0))
VERBOSE = os.getenv("QUOTEX_DEBUG_VERBOSE", "0").strip() == "1"


def log(message: str) -> None:
    print(f"[MMC Quotex Android Collector] {message}", flush=True)


def _decode_png(raw: bytes) -> np.ndarray | None:
    if not raw:
        return None
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is not None and image.size:
        return image
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        fixed = raw.replace(b"\r\n", b"\n")
        image = cv2.imdecode(np.frombuffer(fixed, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is not None and image.size:
            return image
    return None


def adb_screenshot() -> np.ndarray:
    """Capture a complete PNG, retrying and falling back if one read is truncated."""
    commands = [
        ["adb", "exec-out", "screencap", "-p"],
        ["adb", "shell", "screencap", "-p"],
    ]
    last_error = "unknown screenshot error"
    for attempt in range(3):
        for command in commands:
            try:
                proc = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                last_error = str(exc)
                continue
            if proc.returncode != 0 or not proc.stdout:
                last_error = proc.stderr.decode("utf-8", errors="ignore").strip() or "device returned no screenshot"
                continue
            image = _decode_png(proc.stdout)
            if image is not None:
                return image
            last_error = f"PNG input buffer is incomplete (received {len(proc.stdout)} bytes)"
        time.sleep(0.25 * (attempt + 1))
    raise RuntimeError(last_error)


def check_device() -> None:
    proc = subprocess.run(["adb", "get-state"], capture_output=True, text=True, timeout=5, check=False)
    if proc.returncode != 0 or proc.stdout.strip() != "device":
        raise RuntimeError("No authorized Android device found. Enable USB debugging and authorize this laptop.")


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    counts = (mask > 0).sum(axis=0)
    result: list[tuple[int, int]] = []
    active = False
    start = 0
    for x, count in enumerate(counts):
        if count >= 4 and not active:
            start, active = x, True
        if active and (count < 4 or x == len(counts) - 1):
            end = x - 1 if count < 4 else x
            if 2 <= end - start + 1 <= 32:
                result.append((start, end))
            active = False
    return result


def _detect_candles(image: np.ndarray) -> list[dict[str, Any]]:
    h, w = image.shape[:2]
    x0, x1 = 0, int(w * 0.64)
    y0, y1 = int(h * 0.10), int(h * 0.68)
    crop = image[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red = (((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 170)) & (hsv[:, :, 1] > 110) & (hsv[:, :, 2] > 120)).astype(np.uint8) * 255
    green = ((hsv[:, :, 0] > 35) & (hsv[:, :, 0] < 90) & (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 80)).astype(np.uint8) * 255
    mask = cv2.bitwise_or(red, green)
    candles: list[dict[str, Any]] = []
    for xa, xb in _runs(mask):
        band = mask[:, xa:xb + 1]
        ys, xs = np.where(band > 0)
        if len(ys) < 35 or int(ys.max() - ys.min() + 1) < 12:
            continue
        body_counts = (band > 0).sum(axis=1)
        peak = int(body_counts.max())
        body_rows = np.where(body_counts >= max(4, int(peak * 0.50)))[0]
        if len(body_rows) == 0:
            continue
        full_top, full_bottom = int(ys.min()), int(ys.max())
        body_top, body_bottom = int(body_rows.min()), int(body_rows.max())
        center_x = (xa + xb) // 2
        green_pixels = int(green[:, xa:xb + 1].sum() // 255)
        red_pixels = int(red[:, xa:xb + 1].sum() // 255)
        direction = "BUY" if green_pixels >= red_pixels else "SELL"
        scale = 0.001
        high = -full_top * scale
        low = -full_bottom * scale
        if direction == "BUY":
            op = -body_bottom * scale
            cl = -body_top * scale
        else:
            op = -body_top * scale
            cl = -body_bottom * scale
        candles.append({
            "x": center_x,
            "direction": direction,
            "open": op,
            "high": max(high, op, cl),
            "low": min(low, op, cl),
            "close": cl,
            "body_height": max(1, body_bottom - body_top + 1),
            "wick_height": max(1, full_bottom - full_top + 1),
        })
    candles.sort(key=lambda item: item["x"])
    clean: list[dict[str, Any]] = []
    for candle in candles:
        if clean and candle["x"] - clean[-1]["x"] < 10:
            if candle["body_height"] > clean[-1]["body_height"]:
                clean[-1] = candle
        else:
            clean.append(candle)
    return clean


def _make_rows(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    closed = candles[:-1]
    if len(closed) < 8:
        return []
    closed = closed[-40:]
    end_bucket = int(time.time() // PERIOD) * PERIOD - PERIOD
    rows = []
    start = end_bucket - (len(closed) - 1) * PERIOD
    for index, candle in enumerate(closed):
        rows.append({
            "asset": ASSET,
            "period": PERIOD,
            "timestamp": float(start + index * PERIOD),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
        })
    return rows


class Collector:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.last_signature = ""
        self.last_send = 0.0
        self.last_http_error = ""

    def send(self, rows: list[dict[str, Any]]) -> None:
        if not rows or not INGEST_SECRET:
            return
        signature = "|".join(f"{r['timestamp']}:{r['close']}" for r in rows[-5:])
        if signature == self.last_signature and time.monotonic() - self.last_send < 45:
            return

        try:
            response = self.session.post(
                f"{BOT_URL}/quotex/ingest",
                json={"sent_at": time.time(), "candles": rows},
                headers={"X-MMC-Quotex-Key": INGEST_SECRET},
                timeout=10,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            message = f"Render connection failed: {exc}"
            if message != self.last_http_error:
                log(f"ERROR: {message}")
                self.last_http_error = message
            return

        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location", "")
            message = f"Render returned HTTP {response.status_code} redirect{(' to ' + location) if location else ''}. Wait for the latest deployment and retry."
            if message != self.last_http_error:
                log(f"ERROR: {message}")
                self.last_http_error = message
            return

        if not 200 <= response.status_code < 300:
            body = response.text.strip().replace("\r", " ").replace("\n", " ")[:240]
            message = f"Render ingest HTTP {response.status_code}: {body or 'empty response'}"
            if message != self.last_http_error:
                log(f"ERROR: {message}")
                self.last_http_error = message
            return

        try:
            data = response.json()
        except ValueError:
            body = response.text.strip().replace("\r", " ").replace("\n", " ")[:240]
            message = f"Render returned non-JSON success response: {body or 'empty response'}"
            if message != self.last_http_error:
                log(f"ERROR: {message}")
                self.last_http_error = message
            return

        if not data.get("ok"):
            message = f"Render rejected candles: {data.get('error', 'unknown error')}"
            if message != self.last_http_error:
                log(f"ERROR: {message}")
                self.last_http_error = message
            return

        self.last_http_error = ""
        self.last_signature = signature
        self.last_send = time.monotonic()
        log(f"sent {data.get('accepted', len(rows))} screen candles for {ASSET}")


def main() -> int:
    if not INGEST_SECRET:
        log("ERROR: set QUOTEX_INGEST_SECRET before starting")
        return 1
    try:
        check_device()
        log(f"Android device connected; monitoring {ASSET}")
        log("Keep the Quotex app on the 1-minute OTC chart. No orders are automated.")
        collector = Collector()
        delay = 1.0 / FPS
        while True:
            started = time.monotonic()
            image = adb_screenshot()
            candles = _detect_candles(image)
            rows = _make_rows(candles)
            if VERBOSE:
                dirs = "".join("G" if c["direction"] == "BUY" else "R" for c in candles[-12:])
                log(f"detected={len(candles)} closed={max(0, len(candles)-1)} pattern={dirs}")
            collector.send(rows)
            time.sleep(max(0.05, delay - (time.monotonic() - started)))
    except KeyboardInterrupt:
        log("stopped")
        return 0
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
