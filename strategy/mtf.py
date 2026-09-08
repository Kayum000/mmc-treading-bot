"""Pure MTF direction + 1m price-action entry strategy.

5m/15m/30m establish direction. Only when all three agree, 1m searches for
a fresh sweep + displacement + structure break. A confirmed 1m setup remains
valid for a short freshness window so the live signal does not disappear on
the next tick, while a new opposite setup invalidates it.

No MMC, EMA, RSI or MACD is used.
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
    return x.resample(f'{int(minutes)}min', label='right', closed='right').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'
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
    if not _valid(df, lookback + 3):
        return 'neutral'
    for i in range(len(df) - 1, max(lookback + 1, len(df) - 8), -1):
        s = _structure(df.iloc[:i + 1], lookback)
        if s != 'neutral':
            return s
    return 'neutral'


def mtf_states(df):
    frames = {m: _resample_ohlc(df, m) for m in (5, 15, 30)}
    states = {m: _trend_bias(frames[m]) if frames[m] is not None else 'neutral'
              for m in (5, 15, 30)}
    return frames, states


def market_bias(df):
    """Directional bias exists only when 30m, 15m and 5m agree."""
    _, states = mtf_states(df)
    if states[30] == states[15] == states[5] == 'bullish':
        return 'BUY'
    if states[30] == states[15] == states[5] == 'bearish':
        return 'SELL'
    return 'NEUTRAL'


def _one_minute_setup(x, side, sweep_lookback=5):
    """Check a completed 1m sweep/displacement/MSS sequence ending at x."""
    if len(x) < sweep_lookback + 3:
        return False
    candidate = x.iloc[-1]
    sweep_candle = x.iloc[-2]
    prior = x.iloc[:-2].tail(sweep_lookback)
    if prior.empty:
        return False

    prior_high = float(prior['high'].max())
    prior_low = float(prior['low'].min())
    rng = float(candidate['high'] - candidate['low'])
    body = abs(float(candidate['close'] - candidate['open']))
    if rng <= 0 or body / rng < 0.55:
        return False

    if side == 'BUY':
        sweep = float(sweep_candle['low']) < prior_low and float(sweep_candle['close']) > prior_low
        displacement = float(candidate['close']) > float(candidate['open'])
        mss = float(candidate['close']) > prior_high or float(candidate['close']) > float(sweep_candle['high'])
        return sweep and displacement and mss

    sweep = float(sweep_candle['high']) > prior_high and float(sweep_candle['close']) < prior_high
    displacement = float(candidate['close']) < float(candidate['open'])
    mss = float(candidate['close']) < prior_low or float(candidate['close']) < float(sweep_candle['low'])
    return sweep and displacement and mss


def _one_minute_entry(df, side, freshness=2, lookback=5):
    """Allow a confirmed setup to remain valid for up to `freshness` 1m bars."""
    if not _valid(df, lookback + 5):
        return False
    x = df[['open', 'high', 'low', 'close']].copy()
    for c in x.columns:
        x[c] = pd.to_numeric(x[c], errors='coerce')
    x = x.dropna()
    if len(x) < lookback + 5:
        return False

    # Most recent completed 1m bar gets priority. If its setup was just
    # confirmed, keep the signal alive for the next `freshness` bars.
    for age in range(freshness + 1):
        end = len(x) - age
        if end < lookback + 3:
            continue
        window = x.iloc[:end]
        if _one_minute_setup(window, side, lookback):
            return True
    return False


def generate_signal(df):
    frames, states = mtf_states(df)
    if any(frames[m] is None or len(frames[m]) < 6 for m in (5, 15, 30)):
        return Signal('NO_TRADE', 0, 0, 'MTF 5m/15m/30m বিশ্লেষণের জন্য পর্যাপ্ত বন্ধ ক্যান্ডেল নেই।')

    buy_score = sum(states[m] == 'bullish' for m in (5, 15, 30))
    sell_score = sum(states[m] == 'bearish' for m in (5, 15, 30))

    # 1m analysis is NEVER allowed before full 30m+15m+5m alignment.
    if states[30] == states[15] == states[5] == 'bullish':
        if _one_minute_entry(df, 'BUY'):
            return Signal('BUY', buy_score, sell_score,
                          'MTF BUY: 30m+15m+5m aligned; fresh 1m sweep + displacement + MSS confirmed/persistent.')
        return Signal('NO_TRADE', buy_score, sell_score,
                      '30m+15m+5m bullish, কিন্তু valid 1m BUY confirmation নেই।')

    if states[30] == states[15] == states[5] == 'bearish':
        if _one_minute_entry(df, 'SELL'):
            return Signal('SELL', buy_score, sell_score,
                          'MTF SELL: 30m+15m+5m aligned; fresh 1m sweep + displacement + MSS confirmed/persistent.')
        return Signal('NO_TRADE', buy_score, sell_score,
                      '30m+15m+5m bearish, কিন্তু valid 1m SELL confirmation নেই।')

    return Signal('NO_TRADE', buy_score, sell_score,
                  f"MTF alignment incomplete: 30m={states[30]}, 15m={states[15]}, 5m={states[5]}; 1m analysis skipped.")


def level_for_side(df, side, lookback=20):
    """Compatibility helper: returns the latest 5m structural level."""
    frames, _ = mtf_states(df)
    f = frames.get(5)
    if f is None or f.empty:
        return None
    side = str(side).upper()
    if side == 'BUY':
        return ('support', float(f['low'].tail(lookback).min()))
    if side == 'SELL':
        return ('resistance', float(f['high'].tail(lookback).max()))
    return None
