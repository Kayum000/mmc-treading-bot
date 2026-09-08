"""MTF display bias + independent 1m price-action entry strategy.

5m/15m/30m calculate a directional MTF bias for display only.
They do NOT block the 1m entry engine. Entry continues from the confirmed
1m sweep + displacement + structure-break logic with a short freshness window.

The displayed MTF bias is always BUY or SELL. NEUTRAL is never exposed.
When higher-timeframe structure is unavailable or mixed, the latest available
confirmed direction is used, with the latest completed 1m candle as fallback.

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
    """Return BUY or SELL for display; never expose NEUTRAL."""
    frames, states = mtf_states(df)

    if states[30] == states[15] == states[5] == 'bullish':
        return 'BUY'
    if states[30] == states[15] == states[5] == 'bearish':
        return 'SELL'

    # Higher timeframe wins when the MTF states disagree.
    for minutes in (30, 15, 5):
        if states[minutes] == 'bullish':
            return 'BUY'
        if states[minutes] == 'bearish':
            return 'SELL'

    # Final fallback: latest completed 1m candle direction.
    if _valid(df):
        last = df.iloc[-1]
        try:
            return 'BUY' if float(last['close']) >= float(last['open']) else 'SELL'
        except (TypeError, ValueError, KeyError):
            pass

    return 'BUY'


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

    for age in range(freshness + 1):
        end = len(x) - age
        if end < lookback + 3:
            continue
        window = x.iloc[:end]
        if _one_minute_setup(window, side, lookback):
            return True
    return False


def generate_signal(df):
    """Generate entry from 1m PA; MTF is informational and never a gate."""
    frames, states = mtf_states(df)
    # MTF display must always have a direction, but insufficient MTF history
    # must not suppress the independent 1m entry engine.
    buy_score = sum(states[m] == 'bullish' for m in (5, 15, 30))
    sell_score = sum(states[m] == 'bearish' for m in (5, 15, 30))
    bias = market_bias(df)

    if _one_minute_entry(df, 'BUY'):
        return Signal('BUY', buy_score, sell_score,
                      f'1m BUY: sweep + displacement + MSS confirmed/persistent. MTF bias={bias}.')

    if _one_minute_entry(df, 'SELL'):
        return Signal('SELL', buy_score, sell_score,
                      f'1m SELL: sweep + displacement + MSS confirmed/persistent. MTF bias={bias}.')

    return Signal('NO_TRADE', buy_score, sell_score,
                  f'1m entry setup নেই। MTF bias={bias}; MTF entry gate হিসেবে ব্যবহৃত হয়নি।')


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
