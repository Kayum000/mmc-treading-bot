"""Pure MTF direction + 1m price-action entry strategy.

5m/15m/30m only establish direction. When all three agree, the 1m chart
must provide a fresh liquidity sweep, displacement and structure break before
an entry is returned. No MMC, EMA, RSI or MACD is used.
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
    """Only expose a directional bias when 30m, 15m and 5m agree."""
    _, states = mtf_states(df)
    if states[30] == states[15] == states[5] == 'bullish':
        return 'BUY'
    if states[30] == states[15] == states[5] == 'bearish':
        return 'SELL'
    return 'NEUTRAL'


def _one_minute_entry(df, side, lookback=5):
    """Fresh 1m sweep + displacement + MSS confirmation."""
    if not _valid(df, 8):
        return False
    x = df[['open', 'high', 'low', 'close']].tail(max(lookback + 4, 9)).copy()
    for c in x.columns:
        x[c] = pd.to_numeric(x[c], errors='coerce')
    x = x.dropna()
    if len(x) < 8:
        return False

    last = x.iloc[-1]
    prev = x.iloc[-2]
    prior = x.iloc[:-2].tail(lookback)
    if prior.empty:
        return False

    prior_high = float(prior['high'].max())
    prior_low = float(prior['low'].min())
    rng = float(last['high'] - last['low'])
    body = abs(float(last['close'] - last['open']))
    if rng <= 0 or body / rng < 0.55:
        return False

    if side == 'BUY':
        # Previous candle sweeps sell-side liquidity, then latest candle
        # displaces up and closes above the recent 1m structure.
        sweep = float(prev['low']) < prior_low and float(prev['close']) > prior_low
        displacement = float(last['close']) > float(last['open'])
        mss = float(last['close']) > prior_high or float(last['close']) > float(prev['high'])
        return sweep and displacement and mss

    # SELL: previous candle sweeps buy-side liquidity, then latest candle
    # displaces down and closes below the recent 1m structure.
    sweep = float(prev['high']) > prior_high and float(prev['close']) < prior_high
    displacement = float(last['close']) < float(last['open'])
    mss = float(last['close']) < prior_low or float(last['close']) < float(prev['low'])
    return sweep and displacement and mss


def generate_signal(df):
    frames, states = mtf_states(df)
    if any(frames[m] is None or len(frames[m]) < 6 for m in (5, 15, 30)):
        return Signal('NO_TRADE', 0, 0, 'MTF 5m/15m/30m বিশ্লেষণের জন্য পর্যাপ্ত বন্ধ ক্যান্ডেল নেই।')

    buy_score = sum(states[m] == 'bullish' for m in (5, 15, 30))
    sell_score = sum(states[m] == 'bearish' for m in (5, 15, 30))

    # HTF alignment is mandatory before any 1m analysis can trigger.
    if states[30] == states[15] == states[5] == 'bullish':
        if _one_minute_entry(df, 'BUY'):
            return Signal('BUY', buy_score, sell_score,
                          'MTF aligned BUY: 30m+15m+5m bullish; 1m sweep + displacement + MSS confirmed.')
        return Signal('NO_TRADE', buy_score, sell_score,
                      '30m+15m+5m bullish, কিন্তু 1m BUY confirmation এখনো হয়নি।')

    if states[30] == states[15] == states[5] == 'bearish':
        if _one_minute_entry(df, 'SELL'):
            return Signal('SELL', buy_score, sell_score,
                          'MTF aligned SELL: 30m+15m+5m bearish; 1m sweep + displacement + MSS confirmed.')
        return Signal('NO_TRADE', buy_score, sell_score,
                      '30m+15m+5m bearish, কিন্তু 1m SELL confirmation এখনো হয়নি।')

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
