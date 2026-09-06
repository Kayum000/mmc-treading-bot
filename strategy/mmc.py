"""Single canonical Mirror Market Concept (MMC) strategy engine.

This module implements a clean, single-timeframe Mirror Market Cycle:
1) find a confirmed origin/base;
2) find a directional impulse leg from that origin into a confirmed S/R zone;
3) measure the origin-to-zone distance;
4) mirror that same distance back from the zone toward the origin;
5) require fresh rejection and directional confirmation before producing a next-1m entry.

Only completed 1-minute candles are used. No EMA/RSI/MACD and no MTF logic.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import CONFIG


@dataclass(frozen=True)
class Signal:
    action: str
    buy_score: int
    sell_score: int
    reason: str


def _valid(df: pd.DataFrame, minimum: int) -> bool:
    return df is not None and not df.empty and len(df) >= minimum


def market_structure(df: pd.DataFrame, lookback: int = 3) -> str:
    if not _valid(df, lookback + 2):
        return "neutral"
    prior = df.iloc[-lookback - 1:-1]
    last = df.iloc[-1]
    close = float(last["close"])
    if close > float(prior["high"].max()):
        return "bullish_bos"
    if close < float(prior["low"].min()):
        return "bearish_bos"
    return "neutral"


def liquidity_sweep(df: pd.DataFrame, lookback: int = 10) -> str:
    if not _valid(df, lookback + 1):
        return "none"
    prior = df.iloc[-lookback - 1:-1]
    last = df.iloc[-1]
    prior_high = float(prior["high"].max())
    prior_low = float(prior["low"].min())
    sell = float(last["high"]) > prior_high and float(last["close"]) < prior_high
    buy = float(last["low"]) < prior_low and float(last["close"]) > prior_low
    if sell and not buy:
        return "sell_side_rejection"
    if buy and not sell:
        return "buy_side_rejection"
    return "none"


def displacement(df: pd.DataFrame) -> str:
    if not _valid(df, 3):
        return "none"
    previous = df.iloc[-2]
    last = df.iloc[-1]
    previous_range = max(float(previous["high"] - previous["low"]), 1e-12)
    last_range = max(float(last["high"] - last["low"]), 1e-12)
    body = abs(float(last["close"] - last["open"]))
    if body / last_range < 0.65 or last_range < previous_range * 1.10:
        return "none"
    if float(last["close"]) > float(last["open"]):
        return "bullish"
    if float(last["close"]) < float(last["open"]):
        return "bearish"
    return "none"


def _swing_levels(prior: pd.DataFrame) -> tuple[list[float], list[float]]:
    highs: list[float] = []
    lows: list[float] = []
    for i in range(2, len(prior) - 2):
        window = prior.iloc[i - 2:i + 3]
        high = float(prior.iloc[i]["high"])
        low = float(prior.iloc[i]["low"])
        if high >= float(window["high"].max()):
            highs.append(high)
        if low <= float(window["low"].min()):
            lows.append(low)
    return highs, lows


def _cluster_levels(values: list[float], tolerance: float) -> list[dict]:
    if not values:
        return []
    clusters: list[dict] = []
    for value in sorted(float(v) for v in values):
        if not clusters or abs(value - clusters[-1]["price"]) > tolerance:
            clusters.append({"price": value, "touches": 1})
            continue
        cluster = clusters[-1]
        cluster["price"] = (cluster["price"] * cluster["touches"] + value) / (cluster["touches"] + 1)
        cluster["touches"] += 1
    return clusters


def _candle_body_ratio(row) -> float:
    high, low = float(row["high"]), float(row["low"])
    open_, close = float(row["open"]), float(row["close"])
    return abs(close - open_) / max(high - low, 1e-12)


def _mirror_candidate(df: pd.DataFrame, side: str, lookback: int = 20) -> dict | None:
    """Find the latest valid origin -> directional impulse -> zone structure.

    SELL: bullish impulse from an earlier swing-low origin into resistance.
    BUY: bearish impulse from an earlier swing-high origin into support.

    The mirror target is the equal-distance return from the zone toward the
    origin. Therefore the projected target equals the origin by construction;
    this is intentional and avoids inventing an extension not defined by the
    basic mirror-distance model.
    """
    if not _valid(df, lookback + 7):
        return None

    prior = df.iloc[-lookback - 1:-1].copy().reset_index(drop=True)
    ranges = (prior["high"].astype(float) - prior["low"].astype(float)).clip(lower=0)
    median_range = float(ranges.tail(10).median())
    if median_range <= 0:
        return None
    tolerance = max(median_range * 0.08, 1e-12)

    swing_highs, swing_lows = _swing_levels(prior)
    resistance_clusters = _cluster_levels(swing_highs, tolerance)
    support_clusters = _cluster_levels(swing_lows, tolerance)
    last_close = float(prior.iloc[-1]["close"])

    candidates: list[dict] = []
    side = str(side).upper()

    if side == "SELL":
        for zone in resistance_clusters:
            if zone["touches"] < 2 or zone["price"] < last_close - tolerance:
                continue
            z = float(zone["price"])
            for i in range(2, len(prior) - 3):
                window = prior.iloc[i - 2:i + 3]
                origin = float(prior.iloc[i]["low"])
                if origin > float(window["low"].min()) + tolerance:
                    continue
                distance = z - origin
                if distance <= tolerance * 4:
                    continue
                future = prior.iloc[i + 1:]
                if future.empty:
                    continue
                directional_impulses = future.loc[
                    (future["close"].astype(float) > future["open"].astype(float))
                    & (future.apply(_candle_body_ratio, axis=1) >= 0.55)
                ]
                if directional_impulses.empty:
                    continue
                if float(directional_impulses["high"].astype(float).max()) < z - tolerance:
                    continue
                mirror_target = z - distance
                candidates.append({
                    "side": "SELL", "origin": origin, "zone": z,
                    "distance": distance, "mirror_target": mirror_target,
                    "tolerance": tolerance, "zone_touches": int(zone["touches"]),
                    "origin_index": i,
                })

    elif side == "BUY":
        for zone in support_clusters:
            if zone["touches"] < 2 or zone["price"] > last_close + tolerance:
                continue
            z = float(zone["price"])
            for i in range(2, len(prior) - 3):
                window = prior.iloc[i - 2:i + 3]
                origin = float(prior.iloc[i]["high"])
                if origin < float(window["high"].max()) - tolerance:
                    continue
                distance = origin - z
                if distance <= tolerance * 4:
                    continue
                future = prior.iloc[i + 1:]
                if future.empty:
                    continue
                directional_impulses = future.loc[
                    (future["close"].astype(float) < future["open"].astype(float))
                    & (future.apply(_candle_body_ratio, axis=1) >= 0.55)
                ]
                if directional_impulses.empty:
                    continue
                if float(directional_impulses["low"].astype(float).min()) > z + tolerance:
                    continue
                mirror_target = z + distance
                candidates.append({
                    "side": "BUY", "origin": origin, "zone": z,
                    "distance": distance, "mirror_target": mirror_target,
                    "tolerance": tolerance, "zone_touches": int(zone["touches"]),
                    "origin_index": i,
                })

    if not candidates:
        return None
    return max(candidates, key=lambda x: (x["origin_index"], x["zone_touches"]))


def get_mirror_projection(df: pd.DataFrame, side: str, lookback: int = 20) -> dict | None:
    """Public mirror calculation: origin, zone, measured distance and target."""
    return _mirror_candidate(df, side, lookback)


def strong_level_rejection(df: pd.DataFrame, lookback: int = 20) -> str:
    """Confirm rejection directly against the canonical Mirror MMC zone."""
    last = df.iloc[-1] if df is not None and not df.empty else None
    if last is None:
        return "none"

    high, low = float(last["high"]), float(last["low"])
    open_, close = float(last["open"]), float(last["close"])
    candle_range = max(high - low, 1e-12)
    body = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    sweep = liquidity_sweep(df, min(10, len(df) - 1))
    impulse = displacement(df)

    sell_mirror = get_mirror_projection(df, "SELL", lookback)
    buy_mirror = get_mirror_projection(df, "BUY", lookback)

    sell = False
    if sell_mirror is not None:
        resistance = float(sell_mirror["zone"])
        tolerance = float(sell_mirror["tolerance"])
        sell = (
            high >= resistance - tolerance
            and close < resistance
            and close <= low + candle_range * 0.48
            and upper_wick >= max(body * 1.25, candle_range * 0.30)
            and (sweep == "sell_side_rejection" or impulse == "bearish")
        )

    buy = False
    if buy_mirror is not None:
        support = float(buy_mirror["zone"])
        tolerance = float(buy_mirror["tolerance"])
        buy = (
            low <= support + tolerance
            and close > support
            and close >= low + candle_range * 0.52
            and lower_wick >= max(body * 1.25, candle_range * 0.30)
            and (sweep == "buy_side_rejection" or impulse == "bullish")
        )

    if sell and not buy:
        return "strong_resistance_rejection"
    if buy and not sell:
        return "strong_support_rejection"
    return "none"


def final_confirmation(df: pd.DataFrame, side: str, lookback: int = 20) -> bool:
    wanted = str(side).lower()
    rejection = strong_level_rejection(df, lookback)
    mirror = get_mirror_projection(df, wanted.upper(), lookback)
    if wanted == "buy":
        return rejection == "strong_support_rejection" and mirror is not None and (liquidity_sweep(df, 10) == "buy_side_rejection" or displacement(df) == "bullish")
    if wanted == "sell":
        return rejection == "strong_resistance_rejection" and mirror is not None and (liquidity_sweep(df, 10) == "sell_side_rejection" or displacement(df) == "bearish")
    return False


def generate_signal(df: pd.DataFrame) -> Signal:
    minimum = max(CONFIG.sweep_lookback + 1, CONFIG.level_lookback + 5, 27)
    if not _valid(df, minimum):
        return Signal("NO_TRADE", 0, 0, "পরিষ্কার MMC যাচাইয়ের জন্য পর্যাপ্ত বন্ধ ১ মিনিটের ক্যান্ডেল নেই।")

    structure = market_structure(df, CONFIG.swing_lookback)
    sweep = liquidity_sweep(df, CONFIG.sweep_lookback)
    impulse = displacement(df)
    rejection = strong_level_rejection(df, CONFIG.level_lookback)
    buy_mirror = get_mirror_projection(df, "BUY", CONFIG.level_lookback)
    sell_mirror = get_mirror_projection(df, "SELL", CONFIG.level_lookback)

    buy_score = 2 * int(structure == "bullish_bos") + 2 * int(sweep == "buy_side_rejection") + int(impulse == "bullish") + 3 * int(rejection == "strong_support_rejection") + 2 * int(buy_mirror is not None)
    sell_score = 2 * int(structure == "bearish_bos") + 2 * int(sweep == "sell_side_rejection") + int(impulse == "bearish") + 3 * int(rejection == "strong_resistance_rejection") + 2 * int(sell_mirror is not None)

    buy_confirmation = rejection == "strong_support_rejection" and buy_mirror is not None and final_confirmation(df, "buy", CONFIG.level_lookback) and ((sweep == "buy_side_rejection" and impulse == "bullish") or structure == "bullish_bos")
    sell_confirmation = rejection == "strong_resistance_rejection" and sell_mirror is not None and final_confirmation(df, "sell", CONFIG.level_lookback) and ((sweep == "sell_side_rejection" and impulse == "bearish") or structure == "bearish_bos")

    if buy_confirmation and not sell_confirmation:
        m = buy_mirror
        return Signal("BUY", buy_score, sell_score, f"ক্লিন Mirror MMC BUY: origin {m['origin']:.8f} → support {m['zone']:.8f}, mirror distance {m['distance']:.8f}, projected mirror target {m['mirror_target']:.8f}; rejection + bullish confirmation। পরবর্তী 1m candle-এ entry।")
    if sell_confirmation and not buy_confirmation:
        m = sell_mirror
        return Signal("SELL", buy_score, sell_score, f"ক্লিন Mirror MMC SELL: origin {m['origin']:.8f} → resistance {m['zone']:.8f}, mirror distance {m['distance']:.8f}, projected mirror target {m['mirror_target']:.8f}; rejection + bearish confirmation। পরবর্তী 1m candle-এ entry।")
    if buy_confirmation and sell_confirmation:
        return Signal("NO_TRADE", buy_score, sell_score, "একই candle-এ দুই দিকের Mirror MMC confirmation এসেছে; তাই entry নেই।")
    if rejection == "strong_support_rejection":
        return Signal("NO_TRADE", buy_score, sell_score, "Support rejection হয়েছে, কিন্তু valid origin→impulse→mirror projection এবং সম্পূর্ণ bullish confirmation হয়নি; BUY বন্ধ।")
    if rejection == "strong_resistance_rejection":
        return Signal("NO_TRADE", buy_score, sell_score, "Resistance rejection হয়েছে, কিন্তু valid origin→impulse→mirror projection এবং সম্পূর্ণ bearish confirmation হয়নি; SELL বন্ধ।")
    return Signal("NO_TRADE", buy_score, sell_score, "Valid origin→impulse→zone mirror structure এবং confirmation একসঙ্গে তৈরি হয়নি; তাই signal নেই।")


def level_for_side(df: pd.DataFrame, side: str):
    """Return the canonical strong level used by a confirmed Mirror MMC setup."""
    side = str(side).upper()
    if side not in {"BUY", "SELL"}:
        return None
    mirror = get_mirror_projection(df, side, CONFIG.level_lookback)
    if mirror is None:
        return None
    return ("support" if side == "BUY" else "resistance", float(mirror["zone"]))
