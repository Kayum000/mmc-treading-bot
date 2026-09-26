"""Future opportunity scanner with historical validation.

The Future Signals list is intentionally uncapped: it returns every current
setup that passes both the live quality score and a historical walk-forward
validation for the same direction/horizon. Historical results are filters,
not guarantees of future performance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import pandas as pd

from strategy.candle_reaction import generate_candle_reaction_signal
from strategy.adaptive_real import generate_adaptive_signal


MIN_HISTORY = 60
MAX_HORIZON = 15
MIN_BACKTEST_TRADES = 12
MIN_BACKTEST_WIN_RATE = 60.0


@dataclass
class FutureOpportunity:
    rank: int
    horizon_candles: int
    action: str
    score: int
    confidence: float
    entry_window: str
    reason: str
    backtest_win_rate: float
    backtest_trades: int


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


def _signal_for_history(x: pd.DataFrame, strategy_mode: str):
    if strategy_mode == "candle_reaction":
        return generate_candle_reaction_signal(x)
    return generate_adaptive_signal(x)


def _backtest_horizon_accuracy(
    candles: pd.DataFrame,
    action: str,
    horizon: int,
    strategy_mode: str,
) -> tuple[float, int, int]:
    """Walk forward through closed candles and score the exact direction/horizon.

    A historical signal is generated only from candles available at that point;
    the future close is read only afterward to determine whether that signal won.
    """
    if len(candles) <= MIN_HISTORY + horizon:
        return 0.0, 0, 0

    wins = 0
    trades = 0
    start = max(MIN_HISTORY, len(candles) - 240)
    end = len(candles) - horizon
    for i in range(start, end):
        history = candles.iloc[: i + 1]
        signal = _signal_for_history(history, strategy_mode)
        if str(signal.action).upper() != action:
            continue
        trades += 1
        entry = float(candles.iloc[i]["close"])
        exit_price = float(candles.iloc[i + horizon]["close"])
        if (action == "BUY" and exit_price > entry) or (action == "SELL" and exit_price < entry):
            wins += 1

    rate = round((wins / trades) * 100.0, 2) if trades else 0.0
    return rate, trades, wins


def _reason(action: str, trend: str, momentum: str, base_reason: str, horizon: int, win_rate: float, trades: int) -> str:
    bits = [f"পরবর্তী {horizon}টি ১-মিনিট candle window"]
    if trend == action:
        bits.append("EMA20/EMA50 trend alignment")
    if momentum == action:
        bits.append("সাম্প্রতিক momentum alignment")
    bits.append(f"ব্যাকটেস্ট: {win_rate:.1f}% ({trades}টি historical setup)")
    if base_reason:
        bits.append(base_reason)
    return " • ".join(bits)


def scan_future_opportunities(candles: pd.DataFrame, ticks=None, strategy_mode: str = "normal") -> dict:
    if candles is None or len(candles) < MIN_HISTORY:
        return {"ok": False, "error": "Future Signal-এর জন্য অন্তত 60টি বন্ধ ১-মিনিট candle দরকার", "signals": []}

    strategy_mode = str(strategy_mode or "normal").strip().lower()
    if strategy_mode not in {"normal", "candle_reaction"}:
        strategy_mode = "normal"

    x = candles.copy().sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    if len(x) < MIN_HISTORY:
        return {"ok": False, "error": "Future Signal-এর জন্য পর্যাপ্ত closed candle নেই", "signals": []}

    if strategy_mode == "candle_reaction":
        base = generate_candle_reaction_signal(x)
    else:
        base = generate_adaptive_signal(x, ticks=ticks)

    trend, trend_strength = _trend_score(x)
    momentum, momentum_strength = _momentum_score(x)
    base_action = str(base.action).upper()

    candidates = []
    rejected_by_backtest = 0

    # No fixed result count. Horizons remain capped at 15 minutes because
    # this scanner is intended for short-term 1-minute entry opportunities.
    for horizon in range(1, MAX_HORIZON + 1):
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

            if score < 82:
                continue

            win_rate, trades, _wins = _backtest_horizon_accuracy(x, action, horizon, strategy_mode)
            if trades < MIN_BACKTEST_TRADES or win_rate < MIN_BACKTEST_WIN_RATE:
                rejected_by_backtest += 1
                continue

            candidates.append(FutureOpportunity(
                rank=0,
                horizon_candles=horizon,
                action=action,
                score=int(round(score)),
                confidence=round(score / 100.0, 3),
                entry_window=f"পরবর্তী {horizon} candle-এর মধ্যে",
                reason=_reason(action, trend, momentum, str(base.reason), horizon, win_rate, trades),
                backtest_win_rate=win_rate,
                backtest_trades=trades,
            ))

    candidates.sort(key=lambda s: (-s.score, -s.backtest_win_rate, s.horizon_candles, s.action))
    for i, c in enumerate(candidates, 1):
        c.rank = i

    return {
        "ok": True,
        "signals": [asdict(c) for c in candidates],
        "count": len(candidates),
        "strategy_mode": strategy_mode,
        "base_signal": base_action,
        "base_score": int(round(float(base.confidence) * 100)) if base_action in {"BUY", "SELL"} else 0,
        "backtest": {
            "minimum_win_rate": MIN_BACKTEST_WIN_RATE,
            "minimum_trades": MIN_BACKTEST_TRADES,
            "validated_candidates": len(candidates),
            "rejected_by_backtest": rejected_by_backtest,
        },
        "note": "তালিকায় শুধু live quality threshold এবং historical backtest validation—দুই শর্ত পূরণ করা setup থাকে। Backtest ভবিষ্যৎ ফলাফলের গ্যারান্টি নয়।",
    }
