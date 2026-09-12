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
  QUOTEX_ANDROID_ASSET   default USDARS_otc (the pair shown in the user's app)
  QUOTEX_SCREEN_FPS      default 2 screenshots/sec
  QUOTEX_DEBUG_VERBOSE   1 for local detection diagnostics
"""
from __future__ import annotations

import io
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


def adb_screenshot() -> np.ndarray:
    proc = subprocess.run(
        ["adb", "exec-out", "screencap", "-p"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=8,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"ADB screenshot failed: {err or 'device not available'}")
    image = cv2.imdecode(np.frombuffer(proc.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("ADB returned an invalid screenshot")
    return image


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
    # The Quotex portrait layout in the supplied recording places the chart in
    # roughly the upper 60-70% of the screen. Percent-based bounds tolerate
    # different phone resolutions while excluding the trade buttons/indicator.
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
        if len(ys) < 35:
            continue
        # Require a meaningful vertical candle rather than a tiny UI artifact.
        if int(ys.max() - ys.min() + 1) < 12:
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
        # Use screen Y as a monotonic price coordinate. Higher on screen means
        # higher synthetic price; the strategy only uses relative candle shape.
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
    # Deduplicate neighboring detections caused by UI overlays.
    clean: list[dict[str, Any]] = []
    for candle in candles:
        if clean and candle["x"] - clean[-1]["x"] < 10:
            if candle["body_height"] > clean[-1]["body_height"]:
                clean[-1] = candle
        else:
            clean.append(candle)
    return clean


def _make_rows(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Exclude the right-most candle: it is normally the currently forming one.
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

    def send(self, rows: list[dict[str, Any]]) -> None:
        if not rows or not INGEST_SECRET:
            return
        signature = "|".join(f"{r['timestamp']}:{r['close']}" for r in rows[-5:])
        # Avoid repeatedly replacing the same screenshot-derived history.
        if signature == self.last_signature and time.monotonic() - self.last_send < 45:
            return
        response = self.session.post(
            f"{BOT_URL}/quotex/ingest",
            json={"sent_at": time.time(), "candles": rows},
            headers={"X-MMC-Quotex-Key": INGEST_SECRET},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
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
