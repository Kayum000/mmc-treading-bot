"""MM-free EURUSD M1 microstructure engine.

Market bias is always BUY/SELL. A real entry is produced only when a local
liquidity sweep is rejected with a strong displacement candle during the
most liquid 08:00-17:00 UTC window. No MMC, Mirror MMC, RSI, MACD, or MTF
confirmation is used.
"""
from __future__ import annotations

from strategy.mmc import Signal, level_for_side

MIN_HISTORY = 40
STRUCTURE_LOOKBACK = 12
VOL_LOOKBACK = 20
SWEEP_BUFFER_ATR = 0.08
MIN_REJECTION_WICK = 0.35
MIN_BODY_RATIO = 0.45
MIN_RANGE_RATIO = 1.30
SESSION_START_UTC = 8
SESSION_END_UTC = 17


def _valid(df, n=2):
    return df is not None and not df.empty and len(df) >= n


def _range(r):
    return max(float(r["high"]) - float(r["low"]), 1e-12)


def _atr_like(x, n=VOL_LOOKBACK):
    r = (x["high"].astype(float) - x["low"].astype(float)).tail(n)
    return max(float(r.median()), 1e-12)


def _hour_utc(value):
    try:
        ts = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
        if getattr(ts, "tzinfo", None) is not None:
            return ts.hour
        return ts.hour
    except Exception:
        return None


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
    return "BUY" if c >= (rh + rl) / 2.0 else "SELL"


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
    buy = 3.0 if bias == "BUY" else 0.0
    sell = 3.0 if bias == "SELL" else 0.0

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

    expansion = rng / atr
    if expansion >= MIN_RANGE_RATIO and body / rng >= MIN_BODY_RATIO:
        if c > o:
            buy += 2.0
        elif c < o:
            sell += 2.0

    close_pos = (c - l) / rng
    if close_pos >= 0.72:
        buy += 1.0
    elif close_pos <= 0.28:
        sell += 1.0

    return buy, sell, swept_low, swept_high, expansion, bias


def market_bias(df):
    """Always return BUY or SELL once at least two candles exist."""
    if not _valid(df, 2):
        return "BUY"
    return _structure_bias(df.tail(40).copy().reset_index(drop=True))


def generate_signal(df):
    """Produce a trade only for a confirmed liquid-session sweep setup."""
    if not _valid(df, MIN_HISTORY):
        return Signal("NO_TRADE", 0, 0, "MM-free microstructure: insufficient history; market bias is still available.")

    buy, sell, swept_low, swept_high, expansion, bias = _scores(df)
    last = df.iloc[-1]
    hour = _hour_utc(last["timestamp"]) if "timestamp" in df.columns else None
    in_session = hour is not None and SESSION_START_UTC <= hour < SESSION_END_UTC

    if swept_low and bias == "BUY" and buy >= 7.0 and in_session and expansion >= MIN_RANGE_RATIO:
        return Signal("BUY", int(round(buy)), int(round(sell)),
                      f"MM-free microstructure BUY | liquidity sweep-low + rejection + displacement | {hour:02d}:xx UTC | expansion={expansion:.2f}x.")
    if swept_high and bias == "SELL" and sell >= 7.0 and in_session and expansion >= MIN_RANGE_RATIO:
        return Signal("SELL", int(round(buy)), int(round(sell)),
                      f"MM-free microstructure SELL | liquidity sweep-high + rejection + displacement | {hour:02d}:xx UTC | expansion={expansion:.2f}x.")

    session_text = f"{hour:02d}:xx UTC" if hour is not None else "outside session"
    return Signal("NO_TRADE", int(round(buy)), int(round(sell)),
                  f"MM-free microstructure | bias={bias} | waiting for sweep/rejection confirmation | {session_text} | expansion={expansion:.2f}x.")


__all__ = ["Signal", "generate_signal", "market_bias", "level_for_side"]
