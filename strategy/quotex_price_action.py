"""Real-Forex-style market-structure and price-action engine.

The live signal is evaluated on closed 1-minute candles with completed 5m/15m
context. No indicator votes drive the decision. Confidence is a rule-strength
heuristic, not a calibrated probability of winning.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class PriceActionSignal:
    action: str
    confidence: float
    reason: str
    regime: str
    strategy: str
    mmc_analysis: dict


def _clean(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    if candles is None or not isinstance(candles, pd.DataFrame) or candles.empty or not required.issubset(candles.columns):
        return pd.DataFrame(columns=sorted(required))
    x = candles.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        x[col] = pd.to_numeric(x[col], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    v = x[["open", "high", "low", "close"]].to_numpy(dtype=float)
    valid = (np.isfinite(v).all(axis=1) & (x["open"].to_numpy() > 0) & (x["low"].to_numpy() > 0)
             & (x["high"].to_numpy() >= x[["open", "close", "low"]].max(axis=1).to_numpy())
             & (x["low"].to_numpy() <= x[["open", "close", "high"]].min(axis=1).to_numpy()))
    return x.loc[valid].reset_index(drop=True)


def _hold(reason: str, analysis: dict | None = None) -> PriceActionSignal:
    details = dict(analysis or {})
    details.update({"available": bool(details.get("available", False)), "direction": "HOLD",
                    "setup": details.get("setup", "NONE"),
                    "confidence_basis": "rule_strength_not_win_probability", "note": reason,
                    "expiry_minutes": 5})
    return PriceActionSignal("HOLD", 0.0, reason, "NO_TRADE", "FOREX_STRUCTURE_PA_1M_MTF", details)


def _resample_closed(x: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate M1 candles and remove any higher-timeframe bar not fully closed."""
    if x.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    y = x.set_index("timestamp")[["open", "high", "low", "close"]].resample(
        f"{minutes}min", label="left", closed="left", origin="start_day"
    ).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
    last_m1_end = x.iloc[-1]["timestamp"] + pd.Timedelta(minutes=1)
    y = y.loc[y["timestamp"] + pd.Timedelta(minutes=minutes) <= last_m1_end]
    return y.reset_index(drop=True)


def _swings(x: pd.DataFrame, left: int = 2, right: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs, lows = [], []
    if len(x) < left + right + 3:
        return highs, lows
    h, l = x["high"].to_numpy(float), x["low"].to_numpy(float)
    # Only confirmed pivots: right-hand bars have already closed.
    for i in range(left, len(x) - right):
        if h[i] >= max(h[i-left:i+right+1]) and np.count_nonzero(h[i] == h[i-left:i+right+1]) == 1:
            highs.append((i, float(h[i])))
        if l[i] <= min(l[i-left:i+right+1]) and np.count_nonzero(l[i] == l[i-left:i+right+1]) == 1:
            lows.append((i, float(l[i])))
    return highs, lows


def _structure_bias(x: pd.DataFrame) -> tuple[str, dict]:
    highs, lows = _swings(x)
    info = {"swing_highs": [v for _, v in highs[-3:]], "swing_lows": [v for _, v in lows[-3:]]}
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL", info
    hh = highs[-1][1] > highs[-2][1]
    lh = highs[-1][1] < highs[-2][1]
    hl = lows[-1][1] > lows[-2][1]
    ll = lows[-1][1] < lows[-2][1]
    if hh and hl:
        return "BULLISH", info
    if lh and ll:
        return "BEARISH", info
    return "NEUTRAL", info


def generate_quotex_price_action_signal(candles: pd.DataFrame) -> PriceActionSignal:
    """Analyze M1 price action with completed M5/M15 structure and a 5m expiry."""
    x = _clean(candles)
    if len(x) < 180:
        return _hold("Multi-timeframe বিশ্লেষণের জন্য পর্যাপ্ত closed ১-মিনিট candle নেই (কমপক্ষে ১৮০টি দরকার)",
                     {"candle_count": len(x), "available": False})

    m5 = _resample_closed(x, 5)
    m15 = _resample_closed(x, 15)
    if len(m5) < 12 or len(m15) < 8:
        return _hold("বন্ধ ৫-মিনিট/১৫-মিনিট context যথেষ্ট নেই; সিগন্যাল বাদ",
                     {"available": False, "m5_count": len(m5), "m15_count": len(m15)})

    bias5, structure5 = _structure_bias(m5)
    bias15, structure15 = _structure_bias(m15)
    last = x.iloc[-1]
    prior = x.iloc[-31:-1]
    op, high, low, close = (float(last[k]) for k in ("open", "high", "low", "close"))
    candle_range = max(high - low, 1e-12)
    body = abs(close - op)
    upper_wick = high - max(op, close)
    lower_wick = min(op, close) - low
    close_position = (close - low) / candle_range
    # ATR is used only to normalize price distance, not as a directional indicator.
    tr = pd.concat([x["high"] - x["low"],
                    (x["high"] - x["close"].shift(1)).abs(),
                    (x["low"] - x["close"].shift(1)).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-2])
    if not np.isfinite(atr) or atr <= 0:
        return _hold("Price range নির্ভরযোগ্য নয়; সিগন্যাল বাদ", {"available": True})

    recent_high = float(prior["high"].max())
    recent_low = float(prior["low"].min())
    # Liquidity reference levels use confirmed M5 swing points when available.
    swing5_highs, swing5_lows = _swings(m5)
    level_high = swing5_highs[-1][1] if swing5_highs else recent_high
    level_low = swing5_lows[-1][1] if swing5_lows else recent_low
    bullish_sweep = low < level_low and close > level_low and close > op and close_position >= 0.65
    bearish_sweep = high > level_high and close < level_high and close < op and close_position <= 0.35
    bullish_bos = close > recent_high and close > op and close_position >= 0.70 and body >= 0.35 * atr
    bearish_bos = close < recent_low and close < op and close_position <= 0.30 and body >= 0.35 * atr
    bullish_rejection = low <= recent_low + 0.12 * atr and close > recent_low and close > op and lower_wick >= max(body, 0.25 * candle_range) and close_position >= 0.65
    bearish_rejection = high >= recent_high - 0.12 * atr and close < recent_high and close < op and upper_wick >= max(body, 0.25 * candle_range) and close_position <= 0.35

    details = {
        "available": True, "expiry_minutes": 5, "analysis_timeframe": "1m",
        "context_timeframes": ["5m", "15m"], "bias_5m": bias5, "bias_15m": bias15,
        "structure_5m": structure5, "structure_15m": structure15,
        "support": level_low, "resistance": level_high,
        "recent_1m_low": recent_low, "recent_1m_high": recent_high,
        "liquidity_sweep": "bullish" if bullish_sweep else "bearish" if bearish_sweep else None,
        "break_of_structure": "bullish" if bullish_bos else "bearish" if bearish_bos else None,
        "confidence_basis": "rule_strength_not_win_probability",
        "risk_note": "Price-action setups are probabilistic; no signal guarantees profit.",
    }

    # Do not trade against either higher-timeframe structure or when either is unclear.
    if bias5 == "NEUTRAL" or bias15 == "NEUTRAL":
        return _hold("৫-মিনিট/১৫-মিনিট market structure পরিষ্কার নয়; অপেক্ষা", details)
    if bias5 != bias15:
        return _hold("৫-মিনিট ও ১৫-মিনিট market structure পরস্পরবিরোধী; সিগন্যাল বাদ", details)
    if body < 0.18 * atr or candle_range < 0.25 * atr:
        return _hold("Confirmation candle দুর্বল/Doji; সিগন্যাল বাদ", details)

    buy_setup = bullish_sweep or bullish_bos or bullish_rejection
    sell_setup = bearish_sweep or bearish_bos or bearish_rejection
    if buy_setup and sell_setup:
        return _hold("একই candle-এ পরস্পরবিরোধী price-action setup; সিগন্যাল বাদ", details)
    if bias5 == "BULLISH" and buy_setup:
        action = "BUY"
        setup = "LIQUIDITY_SWEEP_RECLAIM" if bullish_sweep else "BREAK_OF_STRUCTURE" if bullish_bos else "DEMAND_REJECTION"
    elif bias5 == "BEARISH" and sell_setup:
        action = "SELL"
        setup = "LIQUIDITY_SWEEP_RECLAIM" if bearish_sweep else "BREAK_OF_STRUCTURE" if bearish_bos else "SUPPLY_REJECTION"
    else:
        return _hold("Higher-timeframe bias ও ১-মিনিট entry confirmation একদিকে মেলেনি; সিগন্যাল বাদ", details)

    confidence = 0.70
    if (bullish_sweep if action == "BUY" else bearish_sweep):
        confidence += 0.06
    if (bullish_bos if action == "BUY" else bearish_bos):
        confidence += 0.05
    if (bullish_rejection if action == "BUY" else bearish_rejection):
        confidence += 0.04
    confidence = min(0.85, confidence)
    details.update({"direction": action, "setup": setup, "confidence": confidence,
                    "confirmation": f"{bias15} 15m + {bias5} 5m structure aligned with 1m {setup.lower()}",
                    "entry_invalidation_level": level_low if action == "BUY" else level_high})
    reason = f"{action}: ১৫-মিনিট ও ৫-মিনিট structure aligned; ১-মিনিটে {setup} confirmation; ৫ মিনিট expiry."
    return PriceActionSignal(action, confidence, reason,
                             "PA_BULLISH" if action == "BUY" else "PA_BEARISH",
                             "FOREX_STRUCTURE_PA_1M_MTF", details)
