"""OCR-derived chart price-scale calibration for Android screenshots."""
from __future__ import annotations

import re
import threading
import time
from typing import Any

from data.otc_markets import normalize_detected_market

_NUMBER_RE = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2,8})?$")
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {}
_ANDROID_CONTEXT: dict[str, Any] = {}

def _number(text: str) -> float | None:
    value = text.strip().replace(" ", "").replace(",", "")
    if not _NUMBER_RE.fullmatch(value):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if number <= 0 or number > 1_000_000_000:
        return None
    return number

def _detect_timeframe(text: str) -> str | None:
    compact = str(text or "").lower().replace(" ", "")
    if "1m" in compact or "1min" in compact or "1minute" in compact:
        return "1m"
    return None


def android_context() -> dict[str, Any]:
    now = time.time()
    with _LOCK:
        asset = _ANDROID_CONTEXT.get("asset")
        asset_age = now - float(_ANDROID_CONTEXT.get("updated_at", 0))
        timeframe = _ANDROID_CONTEXT.get("timeframe")
        timeframe_age = now - float(_ANDROID_CONTEXT.get("timeframe_updated_at", 0))
    return {"asset": asset if asset_age <= 30 else None, "timeframe": timeframe if timeframe_age <= 30 else None, "fresh": asset_age <= 30 and timeframe_age <= 30}


def update_ocr(payload: dict[str, Any]) -> dict[str, Any]:
    raw_text = " ".join(str(block.get("text") or "") for block in (payload.get("blocks") or []) if isinstance(block, dict))
    detected_asset = normalize_detected_market(raw_text)
    timeframe = _detect_timeframe(raw_text)
    asset = str(payload.get("active_asset") or payload.get("asset") or "").strip()
    if detected_asset:
        asset = detected_asset
    asset = asset or "unknown"
    width = int(payload.get("image_width") or 0)
    height = int(payload.get("image_height") or 0)
    blocks = payload.get("blocks") or []
    candidates = []
    if width > 0 and height > 0 and isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "").strip()
            value = _number(text)
            if value is None:
                continue
            try:
                left = float(block["left"]); top = float(block["top"])
                right = float(block["right"]); bottom = float(block["bottom"])
            except (KeyError, TypeError, ValueError):
                continue
            # Price scales normally sit beside the chart. Avoid balances,
            # timers and other numbers near the center/left of the UI.
            cx = (left + right) / 2.0
            if cx < width * 0.62:
                continue
            candidates.append({"value": value, "y": (top + bottom) / 2.0 / height, "x": cx, "text": text})

    # Keep one reading per y-band, preferring the rightmost/highest-confidence
    # candidate. This prevents duplicated OCR blocks from biasing calibration.
    candidates.sort(key=lambda item: item["y"])
    unique = []
    for item in candidates:
        if unique and abs(item["y"] - unique[-1]["y"]) < max(6.0, height * 0.008):
            if item["x"] > unique[-1]["x"]:
                unique[-1] = item
        else:
            unique.append(item)

    calibration = None
    if len(unique) >= 2:
        ys = [float(x["y"]) for x in unique]
        prices = [float(x["value"]) for x in unique]
        ybar = sum(ys) / len(ys)
        pbar = sum(prices) / len(prices)
        denom = sum((y - ybar) ** 2 for y in ys)
        if denom > 1e-9:
            slope = sum((y - ybar) * (p - pbar) for y, p in zip(ys, prices)) / denom
            intercept = pbar - slope * ybar
            predicted = [slope * y + intercept for y in ys]
            ss_res = sum((p - q) ** 2 for p, q in zip(prices, predicted))
            ss_tot = sum((p - pbar) ** 2 for p in prices)
            r2 = 1.0 if ss_tot <= 1e-12 else max(0.0, 1.0 - ss_res / ss_tot)
            monotonic = all(prices[i] > prices[i + 1] for i in range(len(prices) - 1))
            # A chart price scale should decrease as screen Y increases.
            if slope < 0 and monotonic and r2 >= 0.985:
                calibration = {
                    "slope_per_normalized_y": slope,
                    "intercept": intercept,
                    "r2": r2,
                    "anchors": unique[-12:],
                    "source_width": width,
                    "source_height": height,
                    "updated_at": time.time(),
                }

    with _LOCK:
        if detected_asset:
            _ANDROID_CONTEXT["asset"] = detected_asset
            _ANDROID_CONTEXT["updated_at"] = time.time()
        if timeframe:
            _ANDROID_CONTEXT["timeframe"] = timeframe
            _ANDROID_CONTEXT["timeframe_updated_at"] = time.time()
        if calibration is not None:
            _STATE[asset] = calibration
        state = dict(_STATE.get(asset) or {})
    return {
        "ok": True,
        "asset": asset,
        "detected_asset": detected_asset,
        "timeframe": timeframe,
        "numeric_candidates": unique[-20:],
        "calibrated": bool(state),
        "calibration": state or None,
    }

def get_calibration(asset: str | None) -> dict[str, Any] | None:
    if not asset:
        return None
    with _LOCK:
        state = _STATE.get(asset)
        if not state:
            return None
        if time.time() - float(state.get("updated_at", 0)) > 30:
            return None
        return dict(state)

def apply_calibration(probe: dict[str, Any], calibration: dict[str, Any] | None) -> dict[str, Any]:
    if not calibration:
        probe["price_scale_calibrated"] = False
        return probe
    slope = float(calibration["slope_per_normalized_y"])
    intercept = float(calibration["intercept"])
    for candle in probe.get("candles", []):
        rel = candle.get("normalized_ohlc") or {}
        prices = {}
        for key, value in rel.items():
            if value is None:
                continue
            normalized_y = 1.0 - float(value)
            prices[key] = round(slope * normalized_y + intercept, 10)
        candle["price_ohlc"] = prices
    probe["price_scale_calibrated"] = True
    probe["calibration"] = {
        "r2": calibration.get("r2"),
        "anchors": calibration.get("anchors", []),
    }
    return probe
