"""Shadow-only market state scanner for the live dashboard.

This module describes the current quote environment but never changes the
v2.1 signal decision. It is intentionally lightweight and uses only the
same tick history already available to the live Forex path.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from threading import Lock

import numpy as np
import pandas as pd


_CACHE = {}
_CACHE_LOCK = Lock()
_CACHE_TTL = 10.0


def _pip_multiplier(mid: float) -> float:
    return 100.0 if abs(float(mid)) >= 20.0 else 10000.0


def _label_direction(value: float, threshold: float = 0.15) -> str:
    if value > threshold:
        return "UP"
    if value < -threshold:
        return "DOWN"
    return "FLAT"


def scan_market(ticks: pd.DataFrame) -> dict:
    required = {"timestamp", "askPrice", "bidPrice"}
    missing = required - set(ticks.columns)
    if missing:
        raise ValueError(f"missing scanner columns: {sorted(missing)}")

    x = ticks.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    x["askPrice"] = pd.to_numeric(x["askPrice"], errors="coerce")
    x["bidPrice"] = pd.to_numeric(x["bidPrice"], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    if len(x) < 20:
        return {"ok": False, "state": "INSUFFICIENT DATA"}

    x["mid"] = (x["askPrice"] + x["bidPrice"]) / 2.0
    x["spread"] = x["askPrice"] - x["bidPrice"]
    mid = float(x.iloc[-1]["mid"])
    pip = _pip_multiplier(mid)

    def move_pips(n: int) -> float:
        if len(x) <= n:
            n = len(x) - 1
        return float((x.iloc[-1]["mid"] - x.iloc[-1-n]["mid"]) * pip)

    trend_20 = move_pips(20)
    trend_60 = move_pips(min(60, len(x) - 1))
    trend_value = 0.65 * trend_20 + 0.35 * trend_60
    trend = _label_direction(trend_value)

    momentum_10 = move_pips(10)
    momentum_5 = move_pips(5)
    momentum_value = 0.6 * momentum_5 + 0.4 * momentum_10
    momentum = _label_direction(momentum_value, 0.08)

    recent = x.tail(min(100, len(x)))
    range_pips = float((recent["mid"].max() - recent["mid"].min()) * pip)
    returns_pips = recent["mid"].diff().dropna() * pip
    volatility_pips = float(returns_pips.std()) if not returns_pips.empty else 0.0
    if range_pips >= 3.0 or volatility_pips >= 0.12:
        volatility = "HIGH"
    elif range_pips >= 1.2 or volatility_pips >= 0.05:
        volatility = "MEDIUM"
    else:
        volatility = "LOW"

    gaps = x["timestamp"].diff().dt.total_seconds().mul(1000).dropna().tail(50)
    median_gap_ms = float(gaps.median()) if not gaps.empty else None
    if median_gap_ms is None:
        tick_speed = "UNKNOWN"
    elif median_gap_ms <= 200:
        tick_speed = "FAST"
    elif median_gap_ms <= 800:
        tick_speed = "NORMAL"
    else:
        tick_speed = "SLOW"

    spread_pips = float(x.iloc[-1]["spread"] * pip)
    if spread_pips <= 0.8:
        spread_state = "TIGHT"
    elif spread_pips <= 1.5:
        spread_state = "NORMAL"
    else:
        spread_state = "WIDE"

    # Quality is a descriptive market-condition score, not signal confidence.
    score = 0.0
    score += min(abs(trend_value) / 1.0, 1.0) * 25.0
    score += min(abs(momentum_value) / 0.5, 1.0) * 20.0
    score += 20.0 if volatility == "MEDIUM" else 12.0 if volatility == "HIGH" else 8.0
    score += 20.0 if tick_speed == "FAST" else 14.0 if tick_speed == "NORMAL" else 6.0 if tick_speed == "SLOW" else 8.0
    score += 15.0 if spread_state == "TIGHT" else 10.0 if spread_state == "NORMAL" else 2.0
    score = int(round(min(100.0, score)))

    if spread_state == "WIDE":
        state = "POOR"
    elif score >= 70:
        state = "ACTIVE"
    elif score >= 50:
        state = "NORMAL"
    else:
        state = "WEAK"

    last_time = x.iloc[-1]["timestamp"]
    if hasattr(last_time, "to_pydatetime"):
        last_time = last_time.to_pydatetime()
    last_time = last_time.astimezone(timezone.utc)

    return {
        "ok": True,
        "state": state,
        "quality_score": score,
        "trend": trend,
        "trend_pips": round(trend_value, 2),
        "momentum": momentum,
        "momentum_pips": round(momentum_value, 2),
        "volatility": volatility,
        "range_pips": round(range_pips, 2),
        "tick_speed": tick_speed,
        "median_tick_gap_ms": round(median_gap_ms, 0) if median_gap_ms is not None else None,
        "spread": spread_state,
        "spread_pips": round(spread_pips, 2),
        "last_tick_utc": last_time.isoformat(timespec="seconds"),
        "mode": "SHADOW — no signal gating",
    }


def cached_scan(pair: str, fetch_ticks) -> dict:
    """Return a short-lived scan so dashboard polling does not hammer the feed."""
    key = str(pair).strip().upper()
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            return dict(cached[1])
    result = scan_market(fetch_ticks(key, count=1000))
    result["pair"] = key
    with _CACHE_LOCK:
        _CACHE[key] = (now, result)
    return dict(result)
