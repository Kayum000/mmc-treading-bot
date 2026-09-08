"""MM-free EURUSD M1 microstructure engine.

Bias is always BUY/SELL. A real entry requires a prior-candle liquidity
sweep/rejection followed by a confirmed displacement candle in the same
direction during 08:00-17:00 UTC. No MMC, RSI, MACD, or MTF confirmation.
"""
from __future__ import annotations

from strategy.mmc import Signal, level_for_side

MIN_HISTORY = 45
STRUCTURE_LOOKBACK = 12
VOL_LOOKBACK = 20
SWEEP_BUFFER_ATR = 0.08
MIN_REJECTION_WICK = 0.35
MIN_CONFIRM_BODY = 0.45
MIN_EXPANSION = 1.30
MIN_RR = 1.20
COOLDOWN_BARS = 3
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


def market_bias(df):
    """Always return BUY or SELL once at least two candles exist."""
    if not _valid(df, 2):
        return "BUY"
    return _structure_bias(df.tail(40).copy().reset_index(drop=True))


def _confirmed_setup(x):
    """Evaluate sweep on -2 and confirmation/displacement on -1."""
    sweep = x.iloc[-2]
    confirm = x.iloc[-1]
    base = x.iloc[:-2].tail(STRUCTURE_LOOKBACK)
    atr = _atr_like(x.iloc[:-2])
    hi = float(base["high"].max())
    lo = float(base["low"].min())

    so, sc, sh, sl = map(float, (sweep["open"], sweep["close"], sweep["high"], sweep["low"]))
    co, cc, ch, cl = map(float, (confirm["open"], confirm["close"], confirm["high"], confirm["low"]))
    srng = _range(sweep)
    crng = _range(confirm)
    cbody = abs(cc - co)
    lower = min(so, sc) - sl
    upper = sh - max(so, sc)

    bias = _structure_bias(x.iloc[:-2])
    swept_low = sl < lo - atr * SWEEP_BUFFER_ATR and sc > lo
    swept_high = sh > hi + atr * SWEEP_BUFFER_ATR and sc < hi
    reject_low = lower / srng >= MIN_REJECTION_WICK
    reject_high = upper / srng >= MIN_REJECTION_WICK
    expansion = crng / atr
    body_ratio = cbody / crng

    buy_confirm = (
        swept_low and reject_low and bias == "BUY"
        and cc > co and cc > sc
        and body_ratio >= MIN_CONFIRM_BODY
        and expansion >= MIN_EXPANSION
    )
    sell_confirm = (
        swept_high and reject_high and bias == "SELL"
        and cc < co and cc < sc
        and body_ratio >= MIN_CONFIRM_BODY
        and expansion >= MIN_EXPANSION
    )

    buy_rr = sell_rr = 0.0
    if buy_confirm:
        risk = cc - sl
        reward = hi - cc
        buy_rr = reward / risk if risk > 0 else 0.0
    if sell_confirm:
        risk = sh - cc
        reward = cc - lo
        sell_rr = reward / risk if risk > 0 else 0.0

    return buy_confirm and buy_rr >= MIN_RR, sell_confirm and sell_rr >= MIN_RR, expansion, bias, buy_rr, sell_rr


def _recent_confirmation(x):
    """Deterministic cooldown: avoid repeating a same-direction setup recently."""
    if len(x) < MIN_HISTORY + COOLDOWN_BARS:
        return False, False
    buy_recent = sell_recent = False
    start = max(45, len(x) - 1 - COOLDOWN_BARS)
    for end in range(start, len(x) - 1):
        sample = x.iloc[:end + 1]
        b, s, *_ = _confirmed_setup(sample)
        buy_recent |= b
        sell_recent |= s
    return buy_recent, sell_recent


def generate_signal(df):
    """Produce an entry only after causal sweep + confirmation + RR filters."""
    if not _valid(df, MIN_HISTORY):
        return Signal("NO_TRADE", 0, 0, "MM-free microstructure: insufficient history; market bias is still available.")

    x = df.tail(70).copy().reset_index(drop=True)
    last = x.iloc[-1]
    hour = _hour_utc(last["timestamp"]) if "timestamp" in x.columns else None
    in_session = hour is not None and SESSION_START_UTC <= hour < SESSION_END_UTC

    buy_ok, sell_ok, expansion, bias, buy_rr, sell_rr = _confirmed_setup(x)
    buy_recent, sell_recent = _recent_confirmation(x)

    if buy_ok and in_session and not buy_recent:
        return Signal("BUY", 8, 0, f"MM-free BUY | sweep-low + rejection + confirmation | RR={buy_rr:.2f} | {hour:02d}:xx UTC.")
    if sell_ok and in_session and not sell_recent:
        return Signal("SELL", 0, 8, f"MM-free SELL | sweep-high + rejection + confirmation | RR={sell_rr:.2f} | {hour:02d}:xx UTC.")

    session_text = f"{hour:02d}:xx UTC" if hour is not None else "outside session"
    return Signal("NO_TRADE", 5 if bias == "BUY" else 0, 5 if bias == "SELL" else 0,
                  f"MM-free | bias={bias} | waiting for confirmed sweep/displacement | RR(B/S)={buy_rr:.2f}/{sell_rr:.2f} | {session_text} | expansion={expansion:.2f}x.")


__all__ = ["Signal", "generate_signal", "market_bias", "level_for_side"]
