"""Local Windows Quotex App screen collector.

Signal-data-only: this tool captures the user's visible Quotex Windows
application, detects the visible 1-minute candles, detects the currently open
OTC market from Windows UI accessibility text, converts candles into
direction-preserving OHLC-like data, and sends only candle data to MMC.

It does NOT log in, read passwords/SSIDs, click buttons, place orders, or
control the Quotex application.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

import cv2
import numpy as np
import requests
import win32gui
from PIL import ImageGrab

try:
    from pywinauto import Desktop
except Exception:
    Desktop = None

from data.otc_markets import OTC_PAIRS, display_for_asset, normalize_detected_market

PERIOD = 60
BOT_URL = os.getenv("MMC_BOT_URL", "https://mmc-treading-bot.onrender.com").rstrip("/")
INGEST_SECRET = os.getenv("QUOTEX_INGEST_SECRET", "").strip()
FPS = max(1.0, min(float(os.getenv("QUOTEX_WINDOWS_FPS", "2")), 4.0))
VERBOSE = os.getenv("QUOTEX_DEBUG_VERBOSE", "0").strip() == "1"
MARKET_SCAN_SECONDS = 1.0


def log(message: str) -> None:
    print(f"[MMC Quotex Windows App Collector] {message}", flush=True)


def _window_list() -> list[tuple[int, str]]:
    windows: list[tuple[int, str]] = []
    def callback(hwnd: int, _extra: Any) -> None:
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if title:
            windows.append((hwnd, title))
    win32gui.EnumWindows(callback, None)
    return windows


def _select_window() -> int:
    windows = _window_list()
    preferred = [item for item in windows if "quotex" in item[1].lower()]
    ordered = preferred + [item for item in windows if item not in preferred]
    if not ordered:
        raise RuntimeError("No visible Windows application window was found.")
    print()
    print("===============================================================")
    print("Select the open Quotex Windows App window")
    print("===============================================================")
    for index, (_hwnd, title) in enumerate(ordered[:60], 1):
        print(f"  {index:2d}. {title[:110]}")
    print()
    while True:
        choice = input("Enter the number of the Quotex window: ").strip()
        try:
            number = int(choice)
        except ValueError:
            print("Please enter a window number.")
            continue
        if 1 <= number <= min(len(ordered), 60):
            hwnd, title = ordered[number - 1]
            log(f"selected window: {title}")
            return hwnd
        print("That number is not in the list.")


def _client_geometry(hwnd: int) -> tuple[int, int, int, int, int, int, int, int]:
    client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(hwnd)
    if client_right <= client_left or client_bottom <= client_top:
        raise RuntimeError("The selected Quotex window has no usable client area.")
    window_left, window_top, window_right, window_bottom = win32gui.GetWindowRect(hwnd)
    client_screen_left, client_screen_top = win32gui.ClientToScreen(hwnd, (0, 0))
    offset_x = client_screen_left - window_left
    offset_y = client_screen_top - window_top
    client_width = client_right - client_left
    client_height = client_bottom - client_top
    return (window_left, window_top, window_right, window_bottom, offset_x, offset_y, client_width, client_height)


def _capture_visible(hwnd: int) -> np.ndarray | None:
    _wl, _wt, _wr, _wb, _ox, _oy, client_width, client_height = _client_geometry(hwnd)
    client_left, client_top = win32gui.ClientToScreen(hwnd, (0, 0))
    try:
        grabbed = ImageGrab.grab(bbox=(client_left, client_top, client_left + client_width, client_top + client_height), all_screens=True)
    except Exception:
        return None
    image = np.asarray(grabbed.convert("RGB"))
    if image.size == 0:
        return None
    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


def capture_window(hwnd: int) -> np.ndarray:
    image = _capture_visible(hwnd)
    if image is not None:
        return image
    raise RuntimeError("Could not capture the Quotex window. Keep the app open and visible, then restart the collector.")


def _window_accessibility_text(hwnd: int) -> list[str]:
    texts: list[str] = []
    if Desktop is None:
        return texts
    try:
        window = Desktop(backend="uia").window(handle=hwnd)
        for control in window.descendants():
            try:
                value = control.window_text().strip()
            except Exception:
                value = ""
            if value:
                texts.append(value)
            if len(texts) >= 500:
                break
    except Exception:
        return []
    return texts


def detect_active_asset(hwnd: int) -> str | None:
    """Detect the currently selected OTC asset without asking the user."""
    texts = _window_accessibility_text(hwnd)
    for text in texts:
        detected = normalize_detected_market(text)
        if detected:
            return detected
    return normalize_detected_market(" | ".join(texts))


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
            if 2 <= end - start + 1 <= 36:
                result.append((start, end))
            active = False
    return result


def _detect_candles(image: np.ndarray) -> list[dict[str, Any]]:
    h, w = image.shape[:2]
    if w < 300 or h < 220:
        return []
    x0, x1 = int(w * 0.02), int(w * 0.72)
    y0, y1 = int(h * 0.10), int(h * 0.82)
    crop = image[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red = ((((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 170)) & (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 105)).astype(np.uint8) * 255)
    green = (((hsv[:, :, 0] > 32) & (hsv[:, :, 0] < 95) & (hsv[:, :, 1] > 85) & (hsv[:, :, 2] > 75)).astype(np.uint8) * 255)
    mask = cv2.bitwise_or(red, green)
    candles: list[dict[str, Any]] = []
    for xa, xb in _runs(mask):
        band = mask[:, xa:xb + 1]
        ys, _xs = np.where(band > 0)
        if len(ys) < 30 or int(ys.max() - ys.min() + 1) < 10:
            continue
        body_counts = (band > 0).sum(axis=1)
        peak = int(body_counts.max())
        body_rows = np.where(body_counts >= max(4, int(peak * 0.50)))[0]
        if len(body_rows) == 0:
            continue
        full_top, full_bottom = int(ys.min()), int(ys.max())
        body_top, body_bottom = int(body_rows.min()), int(body_rows.max())
        green_pixels = int(green[:, xa:xb + 1].sum() // 255)
        red_pixels = int(red[:, xa:xb + 1].sum() // 255)
        direction = "BUY" if green_pixels >= red_pixels else "SELL"
        scale = 0.001
        high, low = -full_top * scale, -full_bottom * scale
        if direction == "BUY":
            op, cl = -body_bottom * scale, -body_top * scale
        else:
            op, cl = -body_top * scale, -body_bottom * scale
        candles.append({"x": (xa + xb) // 2, "direction": direction, "open": op, "high": max(high, op, cl), "low": min(low, op, cl), "close": cl, "body_height": max(1, body_bottom - body_top + 1)})
    candles.sort(key=lambda item: item["x"])
    clean: list[dict[str, Any]] = []
    for candle in candles:
        if clean and candle["x"] - clean[-1]["x"] < 10:
            if candle["body_height"] > clean[-1]["body_height"]:
                clean[-1] = candle
        else:
            clean.append(candle)
    return clean


def _make_rows(candles: list[dict[str, Any]], asset: str) -> list[dict[str, Any]]:
    closed = candles[:-1]
    if len(closed) < 8:
        return []
    closed = closed[-40:]
    end_bucket = int(time.time() // PERIOD) * PERIOD - PERIOD
    start = end_bucket - (len(closed) - 1) * PERIOD
    return [{"asset": asset, "period": PERIOD, "timestamp": float(start + index * PERIOD), "open": float(candle["open"]), "high": float(candle["high"]), "low": float(candle["low"]), "close": float(candle["close"])} for index, candle in enumerate(closed)]


class Collector:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.last_signature = ""
        self.last_send = 0.0
        self.last_http_error = ""

    def send(self, rows: list[dict[str, Any]], active_asset: str) -> None:
        if not rows or not INGEST_SECRET:
            return
        signature = active_asset + "|" + "|".join(f"{r['timestamp']}:{r['close']}" for r in rows[-5:])
        if signature == self.last_signature and time.monotonic() - self.last_send < 45:
            return
        try:
            response = self.session.post(f"{BOT_URL}/quotex/ingest", json={"sent_at": time.time(), "active_asset": active_asset, "candles": rows}, headers={"X-MMC-Quotex-Key": INGEST_SECRET}, timeout=10, allow_redirects=False)
        except requests.RequestException as exc:
            message = f"Render connection failed: {exc}"
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
            message = "Render returned a non-JSON success response."
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
        log(f"sent {data.get('accepted', len(rows))} screen candles for {display_for_asset(active_asset) or active_asset}")


def main() -> int:
    if not INGEST_SECRET:
        log("ERROR: set QUOTEX_INGEST_SECRET before starting")
        return 1
    try:
        hwnd = _select_window()
        log(f"monitoring all supported OTC markets ({len(OTC_PAIRS)} markets)")
        log("The current OTC market is detected automatically from the open Quotex chart.")
        log("No market name input is required. Keep the Quotex Windows App visible on a 1-minute OTC chart.")
        log("No login, password, SSID, clicks, or orders are automated.")
        collector = Collector()
        delay = 1.0 / FPS
        active_asset: str | None = None
        last_market_scan = 0.0
        while True:
            started = time.monotonic()
            if time.monotonic() - last_market_scan >= MARKET_SCAN_SECONDS:
                detected = detect_active_asset(hwnd)
                last_market_scan = time.monotonic()
                if detected != active_asset:
                    active_asset = detected
                    if active_asset:
                        log(f"detected current market: {display_for_asset(active_asset) or active_asset}")
                    else:
                        log("waiting: current OTC market text was not detected yet")
            if not active_asset:
                time.sleep(max(0.1, delay))
                continue
            image = capture_window(hwnd)
            candles = _detect_candles(image)
            rows = _make_rows(candles, active_asset)
            if VERBOSE:
                dirs = "".join("G" if c["direction"] == "BUY" else "R" for c in candles[-12:])
                log(f"market={active_asset} window={image.shape[1]}x{image.shape[0]} detected={len(candles)} closed={max(0, len(candles)-1)} pattern={dirs}")
            collector.send(rows, active_asset)
            time.sleep(max(0.05, delay - (time.monotonic() - started)))
    except KeyboardInterrupt:
        log("stopped")
        return 0
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
