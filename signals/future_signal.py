"""Future opportunity scanner.

Produces up to 15 ranked forward-looking opportunities from the current closed-candle
setup. These are projections, not guaranteed future outcomes. Each horizon is scored
from the same validated strategy signals plus trend/momentum/structure alignment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import pandas as pd

from strategy.candle_reaction import generate_candle_reaction_signal
from strategy.adaptive_real import generate_adaptive_signal


@dataclass
class FutureOpportunity:
    rank: int
    horizon_candles: int
    action: str
    score: int
    confidence: float
    entry_window: str
    reason: str


def _trend_score(x: pd.DataFrame) -> tuple[str, float]:
    close = pd.to_numeric(x["close"], errors="coerce")
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    last = float(close.iloc[-1])
    if last > ema20 > ema50:
        return "BUY", 1.0
    if last < ema20 < ema50:
        return "SELL", 1.0
    return "HOLD", 0.0


def _momentum_score(x: pd.DataFrame) -> tuple[str, float]:
    close = pd.to_numeric(x["close"], errors="coerce")
    if len(close) < 6:
        return "HOLD", 0.0
    move = float(close.iloc[-1] - close.iloc[-6])
    rng = float((pd.to_numeric(x["high"], errors="coerce") - pd.to_numeric(x["low"], errors="coerce")).tail(10).mean())
    if rng <= 0:
        return "HOLD", 0.0
    strength = min(abs(move) / (rng * 2.5), 1.0)
    if move > 0:
        return "BUY", strength
    if move < 0:
        return "SELL", strength
    return "HOLD", 0.0


def _reason(action: str, trend: str, momentum: str, base_reason: str, horizon: int) -> str:
    bits = [f"পরবর্তী {horizon}টি ১-মিনিট candle window"]
    if trend == action:
        bits.append("EMA20/EMA50 trend alignment")
    if momentum == action:
        bits.append("সাম্প্রতিক momentum alignment")
    if base_reason:
        bits.append(base_reason)
    return " • ".join(bits)


def scan_future_opportunities(candles: pd.DataFrame, ticks=None, strategy_mode: str = "normal", limit: int = 15) -> dict:
    if candles is None or len(candles) < 60:
        return {"ok": False, "error": "Future Signal-এর জন্য অন্তত 60টি বন্ধ ১-মিনিট candle দরকার", "signals": []}

    x = candles.copy().sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    if strategy_mode == "candle_reaction":
        base = generate_candle_reaction_signal(x)
    else:
        base = generate_adaptive_signal(x, ticks=ticks)

    trend, trend_strength = _trend_score(x)
    momentum, momentum_strength = _momentum_score(x)
    base_action = str(base.action).upper()

    candidates = []
    # Near horizons get more weight because the setup is based on the latest
    # closed candle; farther horizons are deliberately penalized.
    for horizon in range(1, 16):
        for action in ("BUY", "SELL"):
            score = 50.0
            if action == base_action:
                score += 24.0 * float(base.confidence)
            if trend == action:
                score += 16.0 * trend_strength
            elif trend in {"BUY", "SELL"}:
                score -= 12.0
            if momentum == action:
                score += 10.0 * momentum_strength
            elif momentum in {"BUY", "SELL"}:
                score -= 7.0
            score -= max(horizon - 1, 0) * 0.9
            if action != base_action:
                score -= 5.0
            score = max(0.0, min(99.0, score))
            if score >= 70:
                candidates.append(FutureOpportunity(
                    rank=0,
                    horizon_candles=horizon,
                    action=action,
                    score=int(round(score)),
                    confidence=round(score / 100.0, 3),
                    entry_window=f"পরবর্তী {horizon} candle-এর মধ্যে",
                    reason=_reason(action, trend, momentum, str(base.reason), horizon),
                ))

    # Keep one opportunity per horizon where possible and avoid a BUY/SELL pair
    # for the same horizon unless both genuinely clear the threshold.
    candidates.sort(key=lambda s: (-s.score, s.horizon_candles, s.action))
    selected=[]
    used_horizons=set()
    for c in candidates:
        if c.horizon_candles not in used_horizons or len(selected) >= limit - 3:
            selected.append(c)
            used_horizons.add(c.horizon_candles)
        if len(selected) >= limit:
            break
    for i, c in enumerate(selected, 1):
        c.rank=i

    return {
        "ok": True,
        "signals": [asdict(c) for c in selected],
        "count": len(selected),
        "strategy_mode": strategy_mode,
        "base_signal": base_action,
        "base_score": int(round(float(base.confidence) * 100)) if base_action in {"BUY","SELL"} else 0,
        "note": "এগুলো বর্তমান closed-candle setup থেকে forward opportunities; নিশ্চিত ভবিষ্যৎ ফলাফল নয়।",
    }
