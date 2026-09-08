"""MM-free EURUSD M1 microstructure engine.

Market bias is always BUY/SELL. A real entry is only produced when a
liquidity sweep, rejection, displacement and directional structure align.
No MMC, Mirror MMC, RSI, MACD, or multi-timeframe confirmation is used.
"""
from __future__ import annotations

from strategy.mmc import Signal, level_for_side

MIN_HISTORY = 40
STRUCTURE_LOOKBACK = 12
VOL_LOOKBACK = 20
SWEEP_BUFFER_ATR = 0.08
MIN_REJECTION_WICK = 0.35
MIN_BODY_RATIO = 0.45
MIN_RANGE_RATIO = 1.15


def _valid(df, n=2):
    return df is not None and not df.empty and len(df) >= n


def _range(r):
    return max(float(r["high"]) - float(r["low"]), 1e-12)


def _body_ratio(r):
    return abs(float(r["close"]) - float(r["open"])) / _range(r)


def _atr_like(x, n=VOL_LOOKBACK):
    r = (x["high"].astype(float) - x["low"].astype(float)).tail(n)
    return max(float(r.median()), 1e-12)


def _structure_bias(x):
    if len(x) < 10:
        return "BUY"
    recent = x.tail(8)
    older = x.iloc[-16:-8] if len(x) >= 16 else x.head(8)
    rh, rl = float(recent["high"].max()), float(recent["low"].min())
    oh, ol = float(older["high"].max()), float(older["low"].min())
    if rh > oh and rl > ol:
        return "BUY"
    if rh < oh and rl < ol:
        return "SELL"
    c = float(x.iloc[-1]["close"])
    mid = (rh + rl) / 2.0
    return "BUY" if c >= mid else "SELL"


def _scores(df):
    x = df.tail(max(MIN_HISTORY, 40)).copy().reset_index(drop=True)
    last = x.iloc[-1]
    prior = x.iloc[:-1].tail(STRUCTURE_LOOKBACK)
    atr = _atr_like(x.iloc[:-1])
    hi = float(prior["high"].max())
    lo = float(prior["low"].min())
    o, c, h, l = map(float, (last["open"], last["close"], last["high"], last["low"]))
    rng = _range(last)
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l

    bias = _structure_bias(x.iloc[:-1])
    buy = 0.0
    sell = 0.0

    # Structural bias is the always-on directional component.
    if bias == "BUY":
        buy += 3.0
    else:
        sell += 3.0

    # Liquidity sweep: wick through a completed local extreme, then close back inside.
    swept_low = l < lo - atr * SWEEP_BUFFER_ATR and c > lo
    swept_high = h > hi + atr * SWEEP_BUFFER_ATR and c < hi
    if swept_low:
        buy += 4.0
        if lower / rng >= MIN_REJECTION_WICK:
            buy += 1.5
    if swept_high:
        sell += 4.0
        if upper / rng >= MIN_REJECTION_WICK:
            sell += 1.5

    # Displacement: the sweep candle must show meaningful body/range expansion.
    median_range = _atr_like(x.iloc[:-1])
    expansion = rng / median_range
    if expansion >= MIN_RANGE_RATIO and body / rng >= MIN_BODY_RATIO:
        if c > o:
            buy += 2.0
        elif c < o:
            sell += 2.0

    # Close location confirms rejection rather than a weak indecision candle.
    close_pos = (c - l) / rng
    if close_pos >= 0.72:
        buy += 1.0
    elif close_pos <= 0.28:
        sell += 1.0

    # Only count a side as a strong setup when the sweep happened on that side.
    return buy, sell, swept_low, swept_high, expansion, bias


def market_bias(df):
    """Always return BUY or SELL once at least two candles exist."""
    if not _valid(df, 2):
        return "BUY"
    return _structure_bias(df.tail(40).copy().reset_index(drop=True))


def generate_signal(df):
    """Produce a trade only for a confirmed sweep/rejection/displacement setup."""
    if not _valid(df, MIN_HISTORY):
        return Signal("NO_TRADE", 0, 0, "MM-free microstructure: insufficient history; market bias is still available.")

    buy, sell, swept_low, swept_high, expansion, bias = _scores(df)

    # Entry must be aligned with structural bias and have an actual liquidity event.
    if swept_low and bias == "BUY" and buy >= 7.0:
        return Signal("BUY", int(round(buy)), int(round(sell)),
                      f"MM-free microstructure BUY | sweep-low + rejection + displacement | expansion={expansion:.2f}x.")
    if swept_high and bias == "SELL" and sell >= 7.0:
        return Signal("SELL", int(round(buy)), int(round(sell)),
                      f"MM-free microstructure SELL | sweep-high + rejection + displacement | expansion={expansion:.2f}x.")

    return Signal("NO_TRADE", int(round(buy)), int(round(sell)),
                  f"MM-free microstructure | bias={bias} | waiting for sweep/rejection confirmation | expansion={expansion:.2f}x.")


__all__ = ["Signal", "generate_signal", "market_bias", "level_for_side"]
