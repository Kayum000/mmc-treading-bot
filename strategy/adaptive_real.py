"""Regime-adaptive candle strategy layer for Real and OTC markets.

Uses candle-based engines:
- trend: EMA20/EMA50 + trend strength
- breakout: rolling 20-bar high/low
- range: Bollinger mean reversion + RSI

The selector uses only data available up to the signal candle, so the backtest
can be run without look-ahead from future candles. The same selector is shared by Real and OTC signal adapters.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class AdaptiveSignal:
    action: str
    confidence: float
    reason: str
    regime: str
    strategy: str


def _prep(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(candles.columns)
    if missing:
        raise ValueError(f"missing candle columns: {sorted(missing)}")
    x = candles.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    for c in ["open", "high", "low", "close"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    return x.reset_index(drop=True)


def _features(x: pd.DataFrame) -> pd.DataFrame:
    y = x.copy()
    close = y["close"]
    high, low = y["high"], y["low"]
    y["ema20"] = close.ewm(span=20, adjust=False).mean()
    y["ema50"] = close.ewm(span=50, adjust=False).mean()
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    y["atr14"] = tr.rolling(14).mean()
    y["atr_pct"] = y["atr14"] / close.replace(0, np.nan)
    y["ema_gap_pct"] = (y["ema20"] - y["ema50"]).abs() / close.replace(0, np.nan)
    y["ema_slope_pct"] = y["ema20"].pct_change(5).abs()
    y["bb_mid"] = close.rolling(20).mean()
    y["bb_std"] = close.rolling(20).std(ddof=0)
    y["bb_upper"] = y["bb_mid"] + 2.0*y["bb_std"]
    y["bb_lower"] = y["bb_mid"] - 2.0*y["bb_std"]
    y["bb_width"] = (y["bb_upper"] - y["bb_lower"]) / y["bb_mid"].replace(0, np.nan)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    y["rsi14"] = 100 - (100 / (1 + rs))
    y["range_high20"] = high.shift(1).rolling(20).max()
    y["range_low20"] = low.shift(1).rolling(20).min()
    return y


def detect_regime(row: pd.Series) -> str:
    """Conservative regime classifier; thresholds are intentionally broad."""
    if pd.isna(row.get("atr_pct")) or pd.isna(row.get("bb_width")) or pd.isna(row.get("ema_gap_pct")):
        return "UNKNOWN"
    vol = float(row["atr_pct"])
    trend = float(row["ema_gap_pct"])
    slope = float(row.get("ema_slope_pct", 0.0) or 0.0)
    width = float(row["bb_width"])
    if vol >= 0.0025:
        return "HIGH_VOLATILITY"
    if trend >= 0.00055 and slope >= 0.00020:
        return "TREND"
    if width <= 0.0018 and vol <= 0.0012:
        return "RANGE"
    if width >= 0.0030 or slope >= 0.00035:
        return "BREAKOUT"
    return "UNCLEAR"


def _trend(row: pd.Series) -> tuple[str, float, str]:
    if row["ema20"] > row["ema50"] and row["close"] > row["ema20"]:
        return "BUY", 0.72, "EMA20 above EMA50 with price above EMA20"
    if row["ema20"] < row["ema50"] and row["close"] < row["ema20"]:
        return "SELL", 0.72, "EMA20 below EMA50 with price below EMA20"
    return "HOLD", 0.0, "trend alignment absent"


def _breakout(row: pd.Series) -> tuple[str, float, str]:
    if pd.notna(row["range_high20"]) and row["close"] > row["range_high20"]:
        return "BUY", 0.75, "20-bar high breakout"
    if pd.notna(row["range_low20"]) and row["close"] < row["range_low20"]:
        return "SELL", 0.75, "20-bar low breakout"
    return "HOLD", 0.0, "breakout not confirmed"


def _range(row: pd.Series) -> tuple[str, float, str]:
    if row["close"] <= row["bb_lower"] and row["rsi14"] <= 35:
        return "BUY", 0.68, "lower Bollinger touch + oversold RSI"
    if row["close"] >= row["bb_upper"] and row["rsi14"] >= 65:
        return "SELL", 0.68, "upper Bollinger touch + overbought RSI"
    return "HOLD", 0.0, "mean-reversion setup absent"


def generate_adaptive_signal(candles: pd.DataFrame, ticks: pd.DataFrame | None = None) -> AdaptiveSignal:
    """Choose one Real-Market strategy from the current market regime."""
    x = _features(_prep(candles))
    if len(x) < 60:
        return AdaptiveSignal("HOLD", 0.0, "insufficient candle history", "UNKNOWN", "NONE")
    row = x.iloc[-1]
    regime = detect_regime(row)
    if regime == "TREND":
        action, conf, reason = _trend(row)
        return AdaptiveSignal(action, conf, reason, regime, "TREND_EMA")
    if regime == "BREAKOUT":
        action, conf, reason = _breakout(row)
        return AdaptiveSignal(action, conf, reason, regime, "BREAKOUT_20")
    if regime == "RANGE":
        action, conf, reason = _range(row)
        return AdaptiveSignal(action, conf, reason, regime, "MEAN_REVERSION_BB_RSI")
    if regime == "HIGH_VOLATILITY":
        action, conf, reason = _breakout(row)
        if action != "HOLD":
            return AdaptiveSignal(action, conf, reason + "; high-volatility filter", regime, "BREAKOUT_20")
        return AdaptiveSignal("HOLD", 0.0, "high volatility without clean breakout", regime, "VOLATILITY_FILTER")
    return AdaptiveSignal("HOLD", 0.0, "market regime unclear", regime, "NO_TRADE")


def backtest_adaptive(candles: pd.DataFrame, min_history: int = 60) -> dict:
    """One-bar-ahead direction backtest with no future information in signals."""
    x = _features(_prep(candles))
    trades = []
    for i in range(max(min_history, 60), len(x)-1):
        row = x.iloc[i]
        regime = detect_regime(row)
        action, conf, strategy, reason = "HOLD", 0.0, "NONE", ""
        if regime == "TREND":
            action, conf, reason = _trend(row); strategy = "TREND_EMA"
        elif regime == "BREAKOUT":
            action, conf, reason = _breakout(row); strategy = "BREAKOUT_20"
        elif regime == "RANGE":
            action, conf, reason = _range(row); strategy = "MEAN_REVERSION_BB_RSI"
        elif regime == "HIGH_VOLATILITY":
            action, conf, reason = _breakout(row); strategy = "BREAKOUT_20"
            if action == "HOLD": strategy = "VOLATILITY_FILTER"
        else:
            strategy = "NO_TRADE"
        if action == "HOLD":
            continue
        next_move = float(x.iloc[i+1]["close"] - x.iloc[i]["close"])
        correct = (action == "BUY" and next_move > 0) or (action == "SELL" and next_move < 0)
        trades.append({"timestamp": x.iloc[i]["timestamp"], "regime": regime, "strategy": strategy, "action": action, "confidence": conf, "correct": bool(correct), "move": next_move, "reason": reason})
    df = pd.DataFrame(trades)
    if df.empty:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "by_regime": {}, "trades_df": df}
    by_regime = {}
    for regime, g in df.groupby("regime"):
        by_regime[regime] = {"trades": int(len(g)), "wins": int(g.correct.sum()), "win_rate": round(float(g.correct.mean())*100, 2)}
    return {"trades": int(len(df)), "wins": int(df.correct.sum()), "losses": int((~df.correct).sum()), "win_rate": round(float(df.correct.mean())*100, 2), "by_regime": by_regime, "trades_df": df}
