"""OHLC-based Quotex indicator analysis.

Volume-family indicators are marked unavailable unless the collector supplies a
real volume/tick-volume column. Higher timeframes are resampled from closed 1m
candles and reported unavailable when history is insufficient.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

TREND_NAMES = [
    "Alligator", "Bollinger Bands", "Envelopes", "Fractal", "Ichimoku Cloud",
    "Keltner channel", "Donchian channel", "Supertrend", "Moving Average",
    "Parabolic SAR", "Zig Zag",
]
OSCILLATOR_NAMES = [
    "ADX", "Aroon", "Awesome Oscillator", "Bears power", "Bulls power", "CCI",
    "DeMarker", "ATR", "MACD", "Momentum", "RSI", "Rate Of Change",
    "Stochastic Oscillator", "Schaff Trend Cycle", "Vortex",
    "Volume Oscillator", "Williams %R", "Weis Waves Volume Oscillator",
]
ALL_NAMES = TREND_NAMES + OSCILLATOR_NAMES


def _prep(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    if candles is None or candles.empty or not required.issubset(candles.columns):
        return pd.DataFrame(columns=sorted(required))
    x = candles.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    for c in ["open", "high", "low", "close"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    # Reject impossible OHLC rows before calculating any indicator.
    finite = np.isfinite(x[["open", "high", "low", "close"]].to_numpy(dtype=float)).all(axis=1)
    valid = (
        finite
        & (x["open"] > 0) & (x["high"] > 0) & (x["low"] > 0) & (x["close"] > 0)
        & (x["high"] >= x[["open", "close", "low"]].max(axis=1))
        & (x["low"] <= x[["open", "close", "high"]].min(axis=1))
    )
    x = x.loc[valid]
    return x.reset_index(drop=True)


def analyze_indicators(candles: pd.DataFrame) -> dict:
    x = _prep(candles)
    # A few calculations (for example the 5-bar Zig Zag proxy) need 6 bars
    # to evaluate safely. After that, each indicator is gated by its own
    # minimum-candle requirement below instead of blocking the whole set at 30.
    if len(x) < 6:
        return {"available": False,
                "reason": "কমপক্ষে ৬টি closed candle দরকার; প্রতিটি indicator-এর নিজস্ব minimum candle count আছে",
                "count": len(x), "score": 0, "signal": "WAIT",
                "indicators": {n: {"value": None, "signal": "N/A"} for n in ALL_NAMES}}
    c, h, l = x.close, x.high, x.low
    prev = c.shift(1)
    tr = pd.concat([h-l, (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    sma = c.rolling(20).mean()
    std = c.rolling(20).std(ddof=0)
    upper, lower = sma + 2*std, sma - 2*std
    ema5, ema10, ema12, ema20, ema26, ema50 = [c.ewm(span=p, adjust=False).mean() for p in (5,10,12,20,26,50)]
    delta = c.diff()
    gain, loss = delta.clip(lower=0).rolling(14).mean(), (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100/(1+rs)
    tp = (h+l+c)/3
    cci = (tp-tp.rolling(20).mean()) / (0.015*tp.rolling(20).apply(lambda a: np.mean(np.abs(a-np.mean(a))), raw=True).replace(0,np.nan))
    lowest, highest = l.rolling(14).min(), h.rolling(14).max()
    stoch = 100*(c-lowest)/(highest-lowest).replace(0,np.nan)
    up_move, down_move = h.diff(), -l.diff()
    plus_dm = up_move.where((up_move>down_move)&(up_move>0),0).rolling(14).sum()
    minus_dm = down_move.where((down_move>up_move)&(down_move>0),0).rolling(14).sum()
    # DMI/ADX uses the 14-bar True Range sum as the DI denominator.
    # Summing a rolling ATR again delays ADX and distorts its scale.
    tr14 = tr.rolling(14).sum()
    plus_di, minus_di = 100*plus_dm/tr14.replace(0,np.nan), 100*minus_dm/tr14.replace(0,np.nan)
    dx = 100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan)
    adx = dx.rolling(14).mean()
    don_hi, don_lo = h.rolling(20).max(), l.rolling(20).min()
    tenkan = (h.rolling(9).max()+l.rolling(9).min())/2
    kijun = (h.rolling(26).max()+l.rolling(26).min())/2
    span_a = (tenkan+kijun)/2
    span_b = (h.rolling(52).max()+l.rolling(52).min())/2
    mid = (h.rolling(20).max()+l.rolling(20).min())/2
    kelt_mid = c.ewm(span=20, adjust=False).mean()
    # Parabolic SAR (step 0.02, max 0.20), with the standard trend extreme
    # point and prior-two-bar constraints.
    sar_values = np.full(len(x), np.nan, dtype=float)
    sar_uptrend = bool(c.iloc[1] >= c.iloc[0])
    sar_af, sar_step, sar_max = 0.02, 0.02, 0.20
    sar_ep = float(h.iloc[1]) if sar_uptrend else float(l.iloc[1])
    sar_values[0] = float(l.iloc[0]) if sar_uptrend else float(h.iloc[0])
    sar_values[1] = sar_values[0] + sar_af*(sar_ep-sar_values[0])
    for i in range(2, len(x)):
        candidate = sar_values[i-1] + sar_af*(sar_ep-sar_values[i-1])
        if sar_uptrend:
            candidate = min(candidate, float(l.iloc[i-1]), float(l.iloc[i-2]))
            if float(l.iloc[i]) < candidate:
                sar_uptrend, candidate, sar_ep, sar_af = False, sar_ep, float(l.iloc[i]), sar_step
            elif float(h.iloc[i]) > sar_ep:
                sar_ep, sar_af = float(h.iloc[i]), min(sar_max, sar_af+sar_step)
        else:
            candidate = max(candidate, float(h.iloc[i-1]), float(h.iloc[i-2]))
            if float(h.iloc[i]) > candidate:
                sar_uptrend, candidate, sar_ep, sar_af = True, sar_ep, float(h.iloc[i]), sar_step
            elif float(l.iloc[i]) < sar_ep:
                sar_ep, sar_af = float(l.iloc[i]), min(sar_max, sar_af+sar_step)
        sar_values[i] = candidate
    # Standard ATR-based Supertrend (period 14, multiplier 3) with recursively
    # constrained final upper/lower bands and direction changes at band breaks.
    st_upper = np.full(len(x), np.nan, dtype=float)
    st_lower = np.full(len(x), np.nan, dtype=float)
    st_direction = np.zeros(len(x), dtype=int)
    st_line = np.full(len(x), np.nan, dtype=float)
    for i in range(len(x)):
        if not np.isfinite(float(atr.iloc[i])):
            continue
        mid_i = (float(h.iloc[i])+float(l.iloc[i]))/2
        basic_upper, basic_lower = mid_i+3*float(atr.iloc[i]), mid_i-3*float(atr.iloc[i])
        if i == 0 or not np.isfinite(st_upper[i-1]):
            st_upper[i], st_lower[i] = basic_upper, basic_lower
            st_direction[i] = 1 if float(c.iloc[i]) >= mid_i else -1
        else:
            st_upper[i] = basic_upper if basic_upper < st_upper[i-1] or float(c.iloc[i-1]) > st_upper[i-1] else st_upper[i-1]
            st_lower[i] = basic_lower if basic_lower > st_lower[i-1] or float(c.iloc[i-1]) < st_lower[i-1] else st_lower[i-1]
            if st_direction[i-1] < 0 and float(c.iloc[i]) > st_upper[i-1]:
                st_direction[i] = 1
            elif st_direction[i-1] > 0 and float(c.iloc[i]) < st_lower[i-1]:
                st_direction[i] = -1
            else:
                st_direction[i] = st_direction[i-1]
        st_line[i] = st_lower[i] if st_direction[i] > 0 else st_upper[i]
    vals = {}
    def add(name, value, sig="NEUTRAL"):
        try:
            v = float(value.iloc[-1]) if isinstance(value, pd.Series) else float(value)
            if not np.isfinite(v): raise ValueError()
            vals[name] = {"value": round(v, 6), "signal": sig}
        except (ValueError, TypeError, IndexError):
            vals[name] = {"value": None, "signal": "N/A",
                          "reason": "পর্যাপ্ত বা পরিবর্তনশীল candle data নেই"}
    def trend_sig(up, down):
        return "BUY" if up else "SELL" if down else "NEUTRAL"
    lastc = float(c.iloc[-1])
    # Trend family: values are proxies where platform-specific algorithms differ.
    # Bill Williams Alligator approximation: SMMA-style jaw/teeth/lips with
    # their customary forward plot offsets represented as lagged series here.
    gator_lips = c.ewm(alpha=1/5, adjust=False).mean().shift(3)
    gator_teeth = c.ewm(alpha=1/8, adjust=False).mean().shift(5)
    gator_jaw = c.ewm(alpha=1/13, adjust=False).mean().shift(8)
    add("Alligator", (gator_lips.iloc[-1]+gator_teeth.iloc[-1]+gator_jaw.iloc[-1])/3,
        trend_sig(gator_lips.iloc[-1]>gator_teeth.iloc[-1]>gator_jaw.iloc[-1],
                  gator_lips.iloc[-1]<gator_teeth.iloc[-1]<gator_jaw.iloc[-1]))
    add("Bollinger Bands", upper.iloc[-1], trend_sig(lastc>sma.iloc[-1], lastc<sma.iloc[-1]))
    # Standard fixed-width Envelopes baseline: 20-SMA +/- 0.1%.
    # Upper-band extensions indicate SELL; lower-band extensions indicate BUY.
    env_up, env_dn = sma*1.001, sma*0.999
    env_signal = "SELL" if lastc > env_up.iloc[-1] else "BUY" if lastc < env_dn.iloc[-1] else "NEUTRAL"
    add("Envelopes", env_up.iloc[-1], env_signal)
    # Find confirmed 5-bar Bill Williams fractal pivots (two closed bars on
    # each side); report the most recent pivot level and breakout direction.
    fractal_highs, fractal_lows = [], []
    for i in range(max(2, len(x)-30), len(x)-2):
        if h.iloc[i] >= h.iloc[i-2:i+3].max():
            fractal_highs.append((i, float(h.iloc[i])))
        if l.iloc[i] <= l.iloc[i-2:i+3].min():
            fractal_lows.append((i, float(l.iloc[i])))
    last_fractal_high = fractal_highs[-1][1] if fractal_highs else None
    last_fractal_low = fractal_lows[-1][1] if fractal_lows else None
    fractal_signal = "BUY" if last_fractal_high is not None and lastc > last_fractal_high else "SELL" if last_fractal_low is not None and lastc < last_fractal_low else "NEUTRAL"
    candidates = ([fractal_highs[-1]] if fractal_highs else []) + ([fractal_lows[-1]] if fractal_lows else [])
    fractal_value = max(candidates, key=lambda p: p[0])[1] if candidates else None
    add("Fractal", fractal_value, fractal_signal)
    add("Ichimoku Cloud", span_a.iloc[-1], trend_sig(lastc>max(span_a.iloc[-1],span_b.iloc[-1]), lastc<min(span_a.iloc[-1],span_b.iloc[-1])))
    add("Keltner channel", kelt_mid.iloc[-1], trend_sig(lastc>kelt_mid.iloc[-1]+2*atr.iloc[-1], lastc<kelt_mid.iloc[-1]-2*atr.iloc[-1]))
    add("Donchian channel", don_hi.iloc[-1], trend_sig(lastc>don_hi.shift(1).iloc[-1], lastc<don_lo.shift(1).iloc[-1]))
    add("Supertrend", st_line[-1], "BUY" if st_direction[-1] > 0 else "SELL" if st_direction[-1] < 0 else "N/A")
    add("Moving Average", ema20.iloc[-1], trend_sig(ema20.iloc[-1]>ema50.iloc[-1], ema20.iloc[-1]<ema50.iloc[-1]))
    add("Parabolic SAR", sar_values[-1], trend_sig(lastc>sar_values[-1], lastc<sar_values[-1]))
    add("Zig Zag", c.pct_change(5).iloc[-1]*100, trend_sig(c.iloc[-1]>c.iloc[-6], c.iloc[-1]<c.iloc[-6]))
    add("ADX", adx.iloc[-1], trend_sig(plus_di.iloc[-1]>minus_di.iloc[-1] and adx.iloc[-1]>20, minus_di.iloc[-1]>plus_di.iloc[-1] and adx.iloc[-1]>20))
    aroon_up = 100*(14-np.argmax(h.iloc[-15:].to_numpy()[::-1]))/14
    aroon_dn = 100*(14-np.argmin(l.iloc[-15:].to_numpy()[::-1]))/14
    add("Aroon", aroon_up, trend_sig(aroon_up>aroon_dn, aroon_dn>aroon_up))
    ao = c.rolling(5).mean()-c.rolling(34).mean()
    add("Awesome Oscillator", ao.iloc[-1], trend_sig(ao.iloc[-1]>0, ao.iloc[-1]<0))
    add("Bears power", (l-ema13(c)).iloc[-1], trend_sig((l-ema13(c)).iloc[-1]>0, (l-ema13(c)).iloc[-1]<0))
    add("Bulls power", (h-ema13(c)).iloc[-1], trend_sig((h-ema13(c)).iloc[-1]>0, (h-ema13(c)).iloc[-1]<0))
    add("CCI", cci.iloc[-1], trend_sig(cci.iloc[-1]>100, cci.iloc[-1]<-100))
    dem_up, dem_dn = h.diff().clip(lower=0).rolling(14).mean(), (-l.diff()).clip(lower=0).rolling(14).mean()
    dem = dem_up/(dem_up+dem_dn).replace(0,np.nan)
    add("DeMarker", dem.iloc[-1], trend_sig(dem.iloc[-1]<0.3, dem.iloc[-1]>0.7))
    add("ATR", atr.iloc[-1], "NEUTRAL")
    macd = ema12-ema26
    add("MACD", macd.iloc[-1]-macd.ewm(span=9,adjust=False).mean().iloc[-1], trend_sig(macd.iloc[-1]>macd.ewm(span=9,adjust=False).mean().iloc[-1], macd.iloc[-1]<macd.ewm(span=9,adjust=False).mean().iloc[-1]))
    add("Momentum", c.diff(10).iloc[-1], trend_sig(c.diff(10).iloc[-1]>0, c.diff(10).iloc[-1]<0))
    add("RSI", rsi.iloc[-1], trend_sig(rsi.iloc[-1]<30, rsi.iloc[-1]>70))
    roc = c.pct_change(12)*100
    add("Rate Of Change", roc.iloc[-1], trend_sig(roc.iloc[-1]>0, roc.iloc[-1]<0))
    add("Stochastic Oscillator", stoch.iloc[-1], trend_sig(stoch.iloc[-1]<20, stoch.iloc[-1]>80))
    # Schaff Trend Cycle proxy: MACD(23, 50), stochastic normalization twice,
    # and EMA(3) smoothing. This keeps STC on its expected 0..100 scale.
    stc_macd = c.ewm(span=23, adjust=False).mean() - c.ewm(span=50, adjust=False).mean()
    stc_low1, stc_high1 = stc_macd.rolling(10).min(), stc_macd.rolling(10).max()
    stc_k1 = (100*(stc_macd-stc_low1)/(stc_high1-stc_low1).replace(0,np.nan)).ewm(span=3, adjust=False).mean()
    stc_low2, stc_high2 = stc_k1.rolling(10).min(), stc_k1.rolling(10).max()
    stc_series = (100*(stc_k1-stc_low2)/(stc_high2-stc_low2).replace(0,np.nan)).ewm(span=3, adjust=False).mean()
    stc_value = stc_series.iloc[-1]
    stc_previous = stc_series.iloc[-2] if len(stc_series) >= 2 else np.nan
    if np.isfinite(stc_value) and np.isfinite(stc_previous):
        stc_signal = "BUY" if stc_previous < 25 <= stc_value and stc_value > stc_previous else "SELL" if stc_previous > 75 >= stc_value and stc_value < stc_previous else "NEUTRAL"
    else:
        stc_signal = "N/A"
    add("Schaff Trend Cycle", stc_value, stc_signal)
    vm_plus = (h-l.shift(1)).abs().rolling(14).sum()
    vm_minus = (l-h.shift(1)).abs().rolling(14).sum()
    add("Vortex", (vm_plus/vm_minus.replace(0,np.nan)).iloc[-1], trend_sig(vm_plus.iloc[-1]>vm_minus.iloc[-1], vm_minus.iloc[-1]>vm_plus.iloc[-1]))
    if "volume" in x.columns or "tick_volume" in x.columns:
        vol_col = "volume" if "volume" in x.columns else "tick_volume"
        vol = pd.to_numeric(x[vol_col], errors="coerce")
        vo = (vol.rolling(5).mean()-vol.rolling(20).mean())/vol.rolling(20).mean().replace(0,np.nan)*100
        add("Volume Oscillator", vo.iloc[-1], trend_sig(vo.iloc[-1]>0, vo.iloc[-1]<0))
        # Weis Waves needs directional wave aggregation; use signed tick-volume proxy and label explicitly.
        signed = vol * np.sign(c.diff().fillna(0))
        add("Weis Waves Volume Oscillator", signed.rolling(5).sum().iloc[-1]-signed.rolling(20).sum().iloc[-1], trend_sig(signed.rolling(5).sum().iloc[-1]>signed.rolling(20).sum().iloc[-1], signed.rolling(5).sum().iloc[-1]<signed.rolling(20).sum().iloc[-1]))
    else:
        vals["Volume Oscillator"] = {"value": None, "signal": "N/A",
                                     "reason": "বাস্তব volume/tick-volume data collector থেকে পাওয়া যায়নি"}
        vals["Weis Waves Volume Oscillator"] = {"value": None, "signal": "N/A",
                                                "reason": "বাস্তব volume/tick-volume data collector থেকে পাওয়া যায়নি"}
    willr = -100*(highest-c)/(highest-lowest).replace(0,np.nan)
    add("Williams %R", willr.iloc[-1], trend_sig(willr.iloc[-1]<-80, willr.iloc[-1]>-20))
    # Require enough closed bars for each lookback before treating its value as valid.
    # A moving EMA can be numerically produced early, but that does not mean its
    # advertised period has enough history behind it.
    minimums = {
        "Alligator": 30, "Bollinger Bands": 20, "Envelopes": 20, "Fractal": 30,
        "Ichimoku Cloud": 52, "Keltner channel": 20, "Donchian channel": 20,
        "Supertrend": 14, "Moving Average": 50, "Parabolic SAR": 30, "Zig Zag": 30,
        "ADX": 27, "Aroon": 30, "Awesome Oscillator": 34, "Bears power": 30,
        "Bulls power": 30, "CCI": 20, "DeMarker": 30, "ATR": 14, "MACD": 34,
        "Momentum": 30, "RSI": 30, "Rate Of Change": 30,
        "Stochastic Oscillator": 30, "Schaff Trend Cycle": 70, "Vortex": 30,
        "Volume Oscillator": 30, "Williams %R": 30,
        "Weis Waves Volume Oscillator": 30,
    }
    for name, required in minimums.items():
        if len(x) < required:
            vals[name] = {"value": None, "signal": "N/A",
                          "reason": f"কমপক্ষে {required}টি closed candle দরকার",
                          "minimum_candles": required}
        elif name in vals:
            vals[name]["minimum_candles"] = required
    votes = [v["signal"] for v in vals.values() if v["signal"] in ("BUY","SELL")]
    buy, sell = votes.count("BUY"), votes.count("SELL")
    total = len(votes)
    score = int(round(100*(buy-sell)/total)) if total else 0
    signal = "BUY" if total >= 10 and score >= 25 else "SELL" if total >= 10 and score <= -25 else "WAIT"
    return {"available": True, "count": len(x), "score": score, "signal": signal,
            "buy_votes": buy, "sell_votes": sell, "usable_indicators": total,
            "minimum_usable_indicators": 10,
            "indicators": vals,
            "note": "এটি indicator vote score, জয়ের সম্ভাবনা নয়; কিছু নামের জন্য OHLC proxy ব্যবহৃত হয়েছে।"}


def ema13(series: pd.Series) -> pd.Series:
    return series.ewm(span=13, adjust=False).mean()


def analyze_timeframes(candles: pd.DataFrame) -> dict:
    """Analyze only closed 1-minute candles; higher timeframe filters are disabled."""
    x = _prep(candles)
    if x.empty:
        return {"1m": {"available": False, "signal": "WAIT", "reason": "candle data নেই"}}
    return {"1m": analyze_indicators(x)}
