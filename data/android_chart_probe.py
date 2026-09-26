"""Screen-chart candle geometry calibration for the Android bridge.

This module intentionally produces pixel-space OHLC candidates only. It never
turns pixels into financial prices or BUY/SELL decisions without a validated
price-scale calibration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CandleCandidate:
    x: int
    left: int
    right: int
    color: str
    top: int
    bottom: int
    body_top: int | None
    body_bottom: int | None
    strength: float

    def as_dict(self, chart_height: int) -> dict[str, Any]:
        h = max(1, chart_height - 1)

        def norm(y: int | None) -> float | None:
            if y is None:
                return None
            return round(max(0.0, min(1.0, 1.0 - (y / h))), 6)

        # Pixel-space OHLC ordering is preserved:
        # open/close come from the detected body edges, while high/low are
        # the detected wick/color extremes. Values are normalized chart units,
        # not market prices.
        return {
            "x": self.x,
            "left": self.left,
            "right": self.right,
            "color": self.color,
            "top": self.top,
            "bottom": self.bottom,
            "body_top": self.body_top,
            "body_bottom": self.body_bottom,
            "strength": self.strength,
            "normalized_ohlc": {
                "high": norm(self.top),
                "low": norm(self.bottom),
                "open": norm(self.body_bottom),
                "close": norm(self.body_top),
            },
        }


def _is_green(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return g > r * 1.18 and g > b * 1.08 and g > 70


def _is_red(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return r > g * 1.18 and r > b * 1.08 and r > 70


def analyze_chart(image, *, max_candles: int = 120) -> dict[str, Any]:
    """Analyze a PIL RGB image without assuming a Quotex screen layout."""
    width, height = image.size
    # Preserve the screenshot aspect ratio so OCR coordinates and candle
    # coordinates remain geometrically compatible.
    scale = min(1.0, 480.0 / max(1, width), 720.0 / max(1, height))
    sample_w = max(1, int(round(width * scale)))
    sample_h = max(1, int(round(height * scale)))
    sample = image.resize((sample_w, sample_h))
    pixels = sample.load()

    # Keep a broad chart search area. Header/footer regions are excluded, but
    # no device-specific x/y coordinates are assumed.
    y0, y1 = int(sample_h * 0.06), int(sample_h * 0.82)

    active: list[tuple[int, int, int]] = []
    green_columns = red_columns = 0
    for x in range(sample_w):
        green_hits = red_hits = 0
        for y in range(y0, y1):
            rgb = pixels[x, y]
            green_hits += _is_green(rgb)
            red_hits += _is_red(rgb)
        if green_hits >= 2:
            green_columns += 1
        if red_hits >= 2:
            red_columns += 1
        if green_hits >= 2 or red_hits >= 2:
            active.append((x, green_hits, red_hits))

    groups: list[list[tuple[int, int, int]]] = []
    current: list[tuple[int, int, int]] = []
    for item in active:
        if current and item[0] > current[-1][0] + 2:
            groups.append(current)
            current = []
        current.append(item)
    if current:
        groups.append(current)

    candles: list[CandleCandidate] = []
    for group in groups:
        left, right = group[0][0], group[-1][0]
        green_score = sum(x[1] for x in group)
        red_score = sum(x[2] for x in group)
        color = "green" if green_score >= red_score else "red"

        top, bottom = sample_h, -1
        body_top, body_bottom = sample_h, -1
        for x in range(max(0, left - 1), min(sample_w, right + 2)):
            for y in range(y0, y1):
                rgb = pixels[x, y]
                green, red = _is_green(rgb), _is_red(rgb)
                if not (green or red):
                    continue
                top = min(top, y)
                bottom = max(bottom, y)
                if (color == "green" and green) or (color == "red" and red):
                    body_top = min(body_top, y)
                    body_bottom = max(body_bottom, y)

        if top >= sample_h or bottom < 0:
            continue

        strength = round(
            min(1.0, max(green_score, red_score) / max(1, len(group) * 8)),
            3,
        )
        candles.append(
            CandleCandidate(
                x=int((left + right) / 2),
                left=left,
                right=right,
                color=color,
                top=top,
                bottom=bottom,
                body_top=body_top if body_top < sample_h else None,
                body_bottom=body_bottom if body_bottom >= 0 else None,
                strength=strength,
            )
        )

    candles.sort(key=lambda c: c.x)
    if len(candles) > max_candles:
        candles = candles[-max_candles:]

    rows = [c.as_dict(sample_h) for c in candles]
    bounds = None
    if rows:
        bounds = {
            "left": min(c["left"] for c in rows),
            "right": max(c["right"] for c in rows),
            "top": min(c["top"] for c in rows),
            "bottom": max(c["bottom"] for c in rows),
        }

    status = (
        "candle-ohlc-relative-detected"
        if rows
        else "color-evidence-detected"
        if (green_columns or red_columns)
        else "no-candle-color-evidence"
    )
    return {
        "green_columns": green_columns,
        "red_columns": red_columns,
        "sample_width": sample_w,
        "sample_height": sample_h,
        "source_width": width,
        "source_height": height,
        "candidate_candles": len(rows),
        "chart_bounds": bounds,
        "candles": rows,
        "status": status,
        "price_scale_calibrated": False,
        "note": (
            "OHLC values are normalized chart-space values. A validated price "
            "scale/asset anchor is still required before these can become market "
            "prices or enter the signal engine."
        ),
    }
