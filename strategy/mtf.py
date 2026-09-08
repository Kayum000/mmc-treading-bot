"""MTF context + market-momentum + respected S/R 1m entry strategy.

5m/15m/30m MTF candles are CONTEXT ONLY. They never block an entry.
The actual BUY/SELL side follows current 1m market momentum/price structure.
Respected 5m S/R zones are detected from confirmed swings, repeated reactions,
and failed breaks. They are quality context, not a hard gate.
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
    """Return current 1m market momentum direction; MTF never blocks it."""
    if not _valid(df, 8):
        return 'BUY'
    x = df[['open', 'high', 'low', 'close']].copy()
    for c in x.columns:
        x[c] = pd.to_numeric(x[c], errors='coerce')
    x = x.dropna()
    if len(x) < 8:
        return 'BUY'
    recent = x.tail(8)
    mid = recent.iloc[:4]
    last = recent.iloc[4:]
    net_move = float(last['close'].iloc[-1] - mid['close'].iloc[0])
    up_bars = int((last['close'] > last['open']).sum())
    down_bars = int((last['close'] < last['open']).sum())
    recent_high = float(recent['high'].max())
    recent_low = float(recent['low'].min())
    last_close = float(recent['close'].iloc[-1])
    span = recent_high - recent_low
    position = (last_close - recent_low) / span if span > 0 else 0.5
    if (net_move > 0 and up_bars >= down_bars) or position >= 0.68:
        return 'BUY'
    if (net_move < 0 and down_bars >= up_bars) or position <= 0.32:
        return 'SELL'
    return 'BUY' if float(x.iloc[-1]['close']) >= float(x.iloc[-1]['open']) else 'SELL'


def _sr_tolerance(f):
    ranges = (f['high'] - f['low']).tail(40)
    median_range = float(ranges.median()) if not ranges.empty else 0.0
    current = float(f['close'].iloc[-1])
    return max(median_range * 0.30, abs(current) * 0.00006)


def _confirmed_pivots(f, wing=2):
    """Confirmed pivots only: last `wing` bars are excluded to avoid lookahead."""
    if len(f) < wing * 2 + 5:
        return [], []
    x = f.iloc[:-wing]
    lows, highs = [], []
    for i in range(wing, len(x) - wing):
        row = x.iloc[i]
        lo = float(row['low'])
        hi = float(row['high'])
        left = x.iloc[i-wing:i]
        right = x.iloc[i+1:i+1+wing]
        if lo <= float(left['low'].min()) and lo <= float(right['low'].min()):
            lows.append((x.index[i], lo))
        if hi >= float(left['high'].max()) and hi >= float(right['high'].max()):
            highs.append((x.index[i], hi))
    return lows, highs


def _cluster_levels(candidates, tolerance):
    if not candidates:
        return []
    ordered = sorted(candidates, key=lambda z: z[1])
    clusters = []
    for ts, price in ordered:
        if not clusters or abs(price - clusters[-1]['price']) > tolerance:
            clusters.append({'price': price, 'times': [ts], 'prices': [price]})
        else:
            c = clusters[-1]
            c['times'].append(ts)
            c['prices'].append(price)
            c['price'] = sum(c['prices']) / len(c['prices'])
    return clusters


def _zone_stats(f, level, side, tolerance):
    """Score a zone using repeated touches, rejection, recency and break penalty."""
    tol = tolerance
    touch = 0
    rejection = 0
    clean_breaks = 0
    retests = 0
    for i in range(1, len(f) - 1):
        r = f.iloc[i]
        o, h, l, c = map(float, (r['open'], r['high'], r['low'], r['close']))
        body = abs(c - o)
        if side == 'support':
            touched = l <= level + tol and h >= level - tol
            rejected = touched and c > level + tol * 0.35 and (min(o, c) - l) >= max(body * 0.6, tol * 0.15)
            broken = c < level - tol
        else:
            touched = l <= level + tol and h >= level - tol
            rejected = touched and c < level - tol * 0.35 and (h - max(o, c)) >= max(body * 0.6, tol * 0.15)
            broken = c > level + tol
        if touched:
            touch += 1
        if rejected:
            rejection += 1
        if broken:
            clean_breaks += 1
            if i + 1 < len(f):
                nxt = float(f.iloc[i+1]['close'])
                if (side == 'support' and nxt > level) or (side == 'resistance' and nxt < level):
                    retests += 1
    age_bars = max(0, len(f) - 1)
    last_touch_age = age_bars
    for i in range(len(f) - 1, 0, -1):
        r = f.iloc[i]
        if float(r['low']) <= level + tol and float(r['high']) >= level - tol:
            last_touch_age = len(f) - 1 - i
            break
    recency = max(0.0, 1.5 - last_touch_age / 20.0)
    score = 1.5 * min(touch, 5) + 2.0 * min(rejection, 3) + 1.0 * min(retests, 2) + recency - 1.5 * min(clean_breaks, 3)
    return {'touches': touch, 'rejections': rejection, 'breaks': clean_breaks,
            'retests': retests, 'recency': recency, 'score': round(score, 2)}


def respected_sr(df, side, lookback=60):
    """Find the nearest *respected* 5m S/R zone for the requested side.

    A zone earns strength from confirmed swing pivots, clustered repeated touches,
    rejection candles, break/retest behavior and recency, while clean breaks reduce it.
    The detector never blocks a signal.
    """
    frames, _ = mtf_states(df)
    f = frames.get(5)
    empty = {'type': 'none', 'price': None, 'near': False, 'distance': None,
             'score': 0.0, 'touches': 0, 'rejections': 0, 'retests': 0}
    if f is None or len(f) < 15:
        return empty
    f = f.tail(lookback)
    tolerance = _sr_tolerance(f)
    lows, highs = _confirmed_pivots(f, wing=2)
    candidates = lows if side == 'BUY' else highs
    clusters = _cluster_levels(candidates, tolerance)
    current = float(f['close'].iloc[-1])
    kind = 'support' if side == 'BUY' else 'resistance'
    scored = []
    for c in clusters:
        level = float(c['price'])
        if side == 'BUY' and level > current + tolerance:
            continue
        if side == 'SELL' and level < current - tolerance:
            continue
        stats = _zone_stats(f, level, kind, tolerance)
        if stats['touches'] < 2 and stats['rejections'] < 1:
            continue
        distance = abs(current - level)
        proximity_bonus = max(0.0, 2.0 - distance / max(tolerance, 1e-9))
        score = stats['score'] + proximity_bonus
        scored.append((score, distance, level, stats))
    if not scored:
        return empty
    scored.sort(key=lambda z: (z[0], -z[1]), reverse=True)
    score, distance, level, stats = scored[0]
    near = distance <= tolerance * 1.5
    return {'type': kind, 'price': level, 'near': near, 'distance': distance,
            'score': round(score, 2), 'touches': stats['touches'],
            'rejections': stats['rejections'], 'retests': stats['retests']}


def _sr_context(df, side, lookback=60):
    return respected_sr(df, side, lookback)


def _one_minute_setup(x, side, sweep_lookback=5):
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
        if _one_minute_setup(x.iloc[:end], side, lookback):
            return True
    return False


def generate_signal(df):
    _, states = mtf_states(df)
    buy_score = sum(states[m] == 'bullish' for m in (5, 15, 30))
    sell_score = sum(states[m] == 'bearish' for m in (5, 15, 30))
    bias = market_bias(df)
    sr = _sr_context(df, bias)
    setup = _one_minute_entry(df, bias)
    level_text = ''
    if sr['price'] is not None:
        level_text = (f' 5m respected {sr["type"]}={sr["price"]:.5f}, '
                      f'score={sr["score"]:.1f}, touches={sr["touches"]}, '
                      f'rejections={sr["rejections"]}')
    if setup and sr['near']:
        return Signal(bias, buy_score, sell_score,
                      f'1m {bias}: market momentum + respected 5m {sr["type"]} + sweep/displacement/MSS confirmed.{level_text} MTF is context only.')
    if setup:
        return Signal(bias, buy_score, sell_score,
                      f'1m {bias}: market momentum + sweep/displacement/MSS confirmed; respected S/R is context only.{level_text} MTF does not block entry.')
    if sr['near']:
        return Signal(bias, buy_score, sell_score,
                      f'Market momentum={bias}; price is near respected 5m {sr["type"]}.{level_text} Waiting for 1m {bias} confirmation; MTF does not block entry.')
    return Signal(bias, buy_score, sell_score,
                  f'Market momentum={bias}; respected 5m S/R context active.{level_text} MTF does not block entry; waiting for 1m {bias} confirmation.')


def level_for_side(df, side, lookback=60):
    sr = _sr_context(df, side, lookback)
    if sr['price'] is None:
        return None
    return sr['type'], sr['price']
