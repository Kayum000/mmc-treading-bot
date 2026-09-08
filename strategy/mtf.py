"""Pure multi-timeframe price-structure strategy using only 5m, 15m and 30m.

No MMC, EMA, RSI, MACD, or other indicator is used for the directional signal.
The 30m and 15m frames establish directional structure; the 5m frame provides
an aligned break-of-structure entry trigger.
"""
from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class Signal:
    action: str
    buy_score: int
    sell_score: int
    reason: str


def _valid(df, n=1):
    return df is not None and not df.empty and len(df) >= n


def _resample_ohlc(df, minutes):
    if not _valid(df) or not isinstance(df.index, pd.DatetimeIndex):
        return None
    x = df[['open', 'high', 'low', 'close']].copy()
    for c in ('open', 'high', 'low', 'close'):
        x[c] = pd.to_numeric(x[c], errors='coerce')
    x = x.dropna()
    if x.empty:
        return None
    return x.resample(
        f'{int(minutes)}min', label='right', closed='right'
    ).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
    }).dropna()


def _structure(df, lookback=3):
    if not _valid(df, lookback + 2):
        return 'neutral'
    previous = df.iloc[-lookback-1:-1]
    close = float(df.iloc[-1]['close'])
    if close > float(previous['high'].max()):
        return 'bullish'
    if close < float(previous['low'].min()):
        return 'bearish'
    return 'neutral'


def _trend_bias(df, lookback=3):
    """Use the most recent confirmed structure break in the HTF window."""
    if not _valid(df, lookback + 3):
        return 'neutral'
    for i in range(len(df) - 1, max(lookback + 1, len(df) - 8), -1):
        sub = df.iloc[:i + 1]
        s = _structure(sub, lookback)
        if s != 'neutral':
            return s
    return 'neutral'


def mtf_states(df):
    frames = {m: _resample_ohlc(df, m) for m in (5, 15, 30)}
    return frames, {m: _trend_bias(frames[m]) if frames[m] is not None else 'neutral'
                    for m in (5, 15, 30)}


def market_bias(df):
    """Visible bias: 30m first, then 15m; neutral if they conflict."""
    _, states = mtf_states(df)
    if states[30] in {'bullish', 'bearish'} and states[15] == states[30]:
        return 'BUY' if states[30] == 'bullish' else 'SELL'
    if states[30] in {'bullish', 'bearish'}:
        return 'BUY' if states[30] == 'bullish' else 'SELL'
    if states[15] in {'bullish', 'bearish'}:
        return 'BUY' if states[15] == 'bullish' else 'SELL'
    return 'NEUTRAL'


def _aligned_entry(states, side):
    want = 'bullish' if side == 'BUY' else 'bearish'
    return states[30] == want and states[15] == want and states[5] == want


def generate_signal(df):
    frames, states = mtf_states(df)
    if any(frames[m] is None or len(frames[m]) < 6 for m in (5, 15, 30)):
        return Signal('NO_TRADE', 0, 0, 'MTF 5m/15m/30m বিশ্লেষণের জন্য পর্যাপ্ত বন্ধ ক্যান্ডেল নেই।')

    buy_ok = _aligned_entry(states, 'BUY')
    sell_ok = _aligned_entry(states, 'SELL')
    buy_score = sum(states[m] == 'bullish' for m in (5, 15, 30))
    sell_score = sum(states[m] == 'bearish' for m in (5, 15, 30))

    if buy_ok and not sell_ok:
        return Signal('BUY', buy_score, sell_score,
                      'Pure MTF BUY: 30m + 15m trend aligned, 5m structure aligned for entry.')
    if sell_ok and not buy_ok:
        return Signal('SELL', buy_score, sell_score,
                      'Pure MTF SELL: 30m + 15m trend aligned, 5m structure aligned for entry.')
    if buy_ok and sell_ok:
        return Signal('NO_TRADE', buy_score, sell_score,
                      'MTF BUY এবং SELL একই সঙ্গে valid নয়; ambiguous structure এ entry বন্ধ।')

    return Signal('NO_TRADE', buy_score, sell_score,
                  f"MTF alignment incomplete: 30m={states[30]}, 15m={states[15]}, 5m={states[5]}.")


def level_for_side(df, side, lookback=20):
    """Compatibility helper: returns the latest 5m structural level."""
    frames, states = mtf_states(df)
    f = frames.get(5)
    if f is None or f.empty:
        return None
    side = str(side).upper()
    if side == 'BUY':
        return ('support', float(f['low'].tail(lookback).min()))
    if side == 'SELL':
        return ('resistance', float(f['high'].tail(lookback).max()))
    return None
