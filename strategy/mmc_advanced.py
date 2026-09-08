"""MM-free EURUSD M1 price-action engine.

The dashboard can always show a BUY/SELL market bias, while the actual
trade signal is allowed to be NO_TRADE when the entry setup is weak.
No MMC, Mirror MMC, EMA, RSI, MACD, or MTF confirmation is used here.
"""
from __future__ import annotations

from strategy.mmc import Signal, level_for_side

MIN_HISTORY = 25
FAST = 8
SLOW = 21
MOMENTUM = 5
RANGE_LOOKBACK = 20


def _valid(df, n=2):
    return df is not None and not df.empty and len(df) >= n


def _rng(r):
    return max(float(r["high"]) - float(r["low"]), 1e-12)


def _body_ratio(r):
    return abs(float(r["close"]) - float(r["open"])) / _rng(r)


def _ema(values, span):
    return values.astype(float).ewm(span=span, adjust=False).mean()


def _scores(df):
    x = df.tail(max(MIN_HISTORY, SLOW + 3)).copy().reset_index(drop=True)
    close = x["close"].astype(float)
    fast = _ema(close, FAST)
    slow = _ema(close, SLOW)
    last = x.iloc[-1]
    prev = x.iloc[-2]
    buy = 0.0
    sell = 0.0

    # Trend direction.
    if fast.iloc[-1] > slow.iloc[-1]:
        buy += 2.0
    elif fast.iloc[-1] < slow.iloc[-1]:
        sell += 2.0

    # EMA slope is deliberately small so it cannot dominate price action.
    if fast.iloc[-1] > fast.iloc[-4]:
        buy += 1.0
    elif fast.iloc[-1] < fast.iloc[-4]:
        sell += 1.0

    # Short momentum.
    anchor = close.iloc[-1 - min(MOMENTUM, len(x) - 2)]
    if close.iloc[-1] > anchor:
        buy += 1.5
    elif close.iloc[-1] < anchor:
        sell += 1.5

    # Current candle quality.
    o, c = float(last["open"]), float(last["close"])
    br = _body_ratio(last)
    if c > o and br >= 0.45:
        buy += 1.5
    elif c < o and br >= 0.45:
        sell += 1.5

    # Previous-candle continuation.
    po, pc = float(prev["open"]), float(prev["close"])
    if c > o and pc > po:
        buy += 0.75
    elif c < o and pc < po:
        sell += 0.75

    # Breakout pressure against the recent completed range.
    prior = x.iloc[:-1].tail(12)
    hi = float(prior["high"].max())
    lo = float(prior["low"].min())
    if c > hi:
        buy += 2.0
    elif c < lo:
        sell += 2.0

    # Rejection pressure.
    h, l = float(last["high"]), float(last["low"])
    upper = h - max(o, c)
    lower = min(o, c) - l
    if lower >= max(upper * 1.4, _rng(last) * 0.25):
        buy += 1.0
    elif upper >= max(lower * 1.4, _rng(last) * 0.25):
        sell += 1.0

    return buy, sell


def market_bias(df):
    """Always return the current directional bias once history exists."""
    if not _valid(df, 2):
        return "BUY"
    buy, sell = _scores(df)
    return "BUY" if buy >= sell else "SELL"


def generate_signal(df):
    """Return a real entry only when directional edge is sufficiently clear."""
    if not _valid(df, MIN_HISTORY):
        return Signal("NO_TRADE", 0, 0, "MM-free PA: insufficient history; market bias is still available.")

    buy, sell = _scores(df)
    bias = "BUY" if buy >= sell else "SELL"
    edge = abs(buy - sell)

    # Avoid turning every M1 fluctuation into a trade.
    if edge < 2.0:
        return Signal(
            "NO_TRADE",
            int(round(buy)),
            int(round(sell)),
            f"MM-free PA | bias={bias} | BUY={buy:.2f} SELL={sell:.2f} | edge={edge:.2f} | weak entry edge.",
        )

    return Signal(
        bias,
        int(round(buy)),
        int(round(sell)),
        f"MM-free PA entry | bias={bias} | BUY={buy:.2f} SELL={sell:.2f} | edge={edge:.2f}.",
    )


__all__ = ["Signal", "generate_signal", "market_bias", "level_for_side"]
