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
    return x.reset_index(drop=True)


def analyze_indicators(candles: pd.DataFrame) -> dict:
    x = _prep(candles)
    if len(x) < 30:
        return {"available": False, "reason": "কমপক্ষে ৩০টি বন্ধ candle দরকার",
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
    plus_di, minus_di = 100*plus_dm/(atr.rolling(14).sum().replace(0,np.nan)), 100*minus_dm/(atr.rolling(14).sum().replace(0,np.nan))
    dx = 100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan)
    adx = dx.rolling(14).mean()
    don_hi, don_lo = h.rolling(20).max(), l.rolling(20).min()
    tenkan = (h.rolling(9).max()+l.rolling(9).min())/2
    kijun = (h.rolling(26).max()+l.rolling(26).min())/2
    span_a = (tenkan+kijun)/2
    span_b = (h.rolling(52).max()+l.rolling(52).min())/2
    mid = (h.rolling(20).max()+l.rolling(20).min())/2
    kelt_mid = c.ewm(span=20, adjust=False).mean()
    sar_proxy = l.rolling(2).min() if c.iloc[-1] >= c.iloc[-2] else h.rolling(2).max()
    vals = {}
    def add(name, value, sig="NEUTRAL"):
        try:
            v = float(value.iloc[-1]) if isinstance(value, pd.Series) else float(value)
            if not np.isfinite(v): raise ValueError()
            vals[name] = {"value": round(v, 6), "signal": sig}
        except (ValueError, TypeError, IndexError):
            vals[name] = {"value": None, "signal": "N/A"}
    def trend_sig(up, down):
        return "BUY" if up else "SELL" if down else "NEUTRAL"
    lastc = float(c.iloc[-1])
    # Trend family: values are proxies where platform-specific algorithms differ.
    add("Alligator", (ema5.iloc[-1]+ema10.iloc[-1]+ema20.iloc[-1])/3, trend_sig(ema5.iloc[-1]>ema10.iloc[-1]>ema20.iloc[-1], ema5.iloc[-1]<ema10.iloc[-1]<ema20.iloc[-1]))
    add("Bollinger Bands", upper.iloc[-1], trend_sig(lastc>sma.iloc[-1], lastc<sma.iloc[-1]))
    env_up, env_dn = sma*1.025, sma*0.975
    add("Envelopes", env_up.iloc[-1], trend_sig(lastc>env_up.iloc[-1], lastc<env_dn.iloc[-1]))
    fractal = "BUY" if lastc > h.iloc[-6:-1].max() else "SELL" if lastc < l.iloc[-6:-1].min() else "NEUTRAL"
    add("Fractal", lastc, fractal)
    add("Ichimoku Cloud", span_a.iloc[-1], trend_sig(lastc>max(span_a.iloc[-1],span_b.iloc[-1]), lastc<min(span_a.iloc[-1],span_b.iloc[-1])))
    add("Keltner channel", kelt_mid.iloc[-1], trend_sig(lastc>kelt_mid.iloc[-1]+2*atr.iloc[-1], lastc<kelt_mid.iloc[-1]-2*atr.iloc[-1]))
    add("Donchian channel", don_hi.iloc[-1], trend_sig(lastc>don_hi.shift(1).iloc[-1], lastc<don_lo.shift(1).iloc[-1]))
    add("Supertrend", kelt_mid.iloc[-1] + (3*atr.iloc[-1] if lastc < kelt_mid.iloc[-1] else -3*atr.iloc[-1]), trend_sig(lastc>kelt_mid.iloc[-1], lastc<kelt_mid.iloc[-1]))
    add("Moving Average", ema20.iloc[-1], trend_sig(ema20.iloc[-1]>ema50.iloc[-1], ema20.iloc[-1]<ema50.iloc[-1]))
    add("Parabolic SAR", sar_proxy.iloc[-1], trend_sig(lastc>sar_proxy.iloc[-1], lastc<sar_proxy.iloc[-1]))
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
    stc_proxy = (macd.ewm(span=10,adjust=False).mean()-macd.ewm(span=20,adjust=False).mean()).iloc[-1]
    add("Schaff Trend Cycle", stc_proxy, trend_sig(stc_proxy>0, stc_proxy<0))
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
        vals["Volume Oscillator"] = {"value": None, "signal": "N/A"}
        vals["Weis Waves Volume Oscillator"] = {"value": None, "signal": "N/A"}
    willr = -100*(highest-c)/(highest-lowest).replace(0,np.nan)
    add("Williams %R", willr.iloc[-1], trend_sig(willr.iloc[-1]<-80, willr.iloc[-1]>-20))
    votes = [v["signal"] for v in vals.values() if v["signal"] in ("BUY","SELL")]
    buy, sell = votes.count("BUY"), votes.count("SELL")
    total = len(votes)
    score = int(round(100*(buy-sell)/total)) if total else 0
    signal = "BUY" if score >= 25 else "SELL" if score <= -25 else "WAIT"
    return {"available": True, "count": len(x), "score": score, "signal": signal,
            "buy_votes": buy, "sell_votes": sell, "usable_indicators": total,
            "indicators": vals,
            "note": "এটি indicator vote score, জয়ের সম্ভাবনা নয়; কিছু নামের জন্য OHLC proxy ব্যবহৃত হয়েছে।"}


def ema13(series: pd.Series) -> pd.Series:
    return series.ewm(span=13, adjust=False).mean()


def analyze_timeframes(candles: pd.DataFrame) -> dict:
    x = _prep(candles)
    if x.empty:
        return {tf: {"available": False, "signal": "WAIT", "reason": "candle data নেই"} for tf in ("1m","5m","15m")}
    out = {"1m": analyze_indicators(x)}
    indexed = x.set_index("timestamp")
    for tf, rule, minimum in (("5m","5min",60), ("15m","15min",60)):
        bars = indexed.resample(rule, label="left", closed="left").agg(
            {"open":"first","high":"max","low":"min","close":"last"}
        ).dropna().reset_index()
        result = analyze_indicators(bars)
        if len(bars) < minimum:
            result.update({"available": False, "signal": "WAIT",
                           "reason": f"{tf} বিশ্লেষণের জন্য প্রায় {minimum}টি resampled candle দরকার; আছে {len(bars)}টি"})
        out[tf] = result
    return out
