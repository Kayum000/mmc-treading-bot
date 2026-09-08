"""MM-free always-direction EURUSD M1 strategy.

Every valid M1 candle receives a directional decision: BUY or SELL.
The engine uses raw OHLC price action only; no MMC, Mirror Zone, EMA, RSI,
MACD, or MTF confirmation is required.

The score is used to choose the stronger direction, not to produce NO_TRADE.
"""
from __future__ import annotations

from strategy.mmc import Signal

LOOKBACK = 20
SHORT_LOOKBACK = 5
BREAKOUT_LOOKBACK = 12
VOL_LOOKBACK = 20


def _valid(df, n=2):
    return df is not None and not df.empty and len(df) >= n


def _rng(r):
    return max(float(r["high"]) - float(r["low"]), 1e-12)


def _body(r):
    return abs(float(r["close"]) - float(r["open"])) / _rng(r)


def _direction_scores(df):
    buy = 0.0
    sell = 0.0
    x = df.tail(max(LOOKBACK, SHORT_LOOKBACK + 2)).reset_index(drop=True)
    last = x.iloc[-1]
    prev = x.iloc[-2]

    o = float(last["open"])
    h = float(last["high"])
    l = float(last["low"])
    c = float(last["close"])
    r = _rng(last)

    body = _body(last)
    if c > o:
        buy += 2.0 + body
    elif c < o:
        sell += 2.0 + body

    n = min(SHORT_LOOKBACK, len(x) - 1)
    anchor = float(x.iloc[-1 - n]["close"])
    if c > anchor:
        buy += 2.0
    elif c < anchor:
        sell += 2.0

    prior = x.iloc[:-1].tail(BREAKOUT_LOOKBACK)
    if not prior.empty:
        hi = float(prior["high"].max())
        lo = float(prior["low"].min())
        if c > hi:
            buy += 3.0
        if c < lo:
            sell += 3.0
        span = max(hi - lo, 1e-12)
        pos = (c - lo) / span
        if pos >= 0.65:
            buy += 1.0
        elif pos <= 0.35:
            sell += 1.0

    ranges = (x["high"].astype(float) - x["low"].astype(float)).iloc[:-1].tail(VOL_LOOKBACK)
    if len(ranges) >= 5:
        median = max(float(ranges.median()), 1e-12)
        if r >= median * 1.20:
            if c > o:
                buy += 2.0
            elif c < o:
                sell += 2.0

    upper = h - max(o, c)
    lower = min(o, c) - l
    if lower > upper * 1.35 and lower > r * 0.25:
        buy += 1.5
    if upper > lower * 1.35 and upper > r * 0.25:
        sell += 1.5

    pc = float(prev["close"])
    if c > pc:
        buy += 0.75
    elif c < pc:
        sell += 0.75

    return buy, sell


def generate_signal(df):
    """Always return BUY or SELL once two M1 candles are available."""
    if not _valid(df, 2):
        return Signal("BUY", 0, 0, "MM-free directional fallback: insufficient history.")

    buy, sell = _direction_scores(df)
    action = "BUY" if buy >= sell else "SELL"
    margin = abs(buy - sell)
    reason = (
        f"MM-free Always-Direction PA | BUY={buy:.2f} SELL={sell:.2f} "
        f"| selected={action} | edge={margin:.2f}"
    )
    return Signal(action, int(round(buy)), int(round(sell)), reason)


__all__ = ["Signal", "generate_signal"]
