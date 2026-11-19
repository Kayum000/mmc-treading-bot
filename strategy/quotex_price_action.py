"""M1 price-action and market-structure signal engine.

Signals come from completed-candle liquidity sweeps, BOS and level rejections.
The 127 technical checks are calculated for the dashboard popup only; they do
not create or override trade direction. M5/M15 provide higher-timeframe context.
Confidence is a rule-strength heuristic, not a calibrated probability of winning.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class PriceActionSignal:
    action: str
    confidence: float
    reason: str
    regime: str
    strategy: str
    mmc_analysis: dict


def _clean(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    if candles is None or not isinstance(candles, pd.DataFrame) or candles.empty or not required.issubset(candles.columns):
        return pd.DataFrame(columns=sorted(required))
    x = candles.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        x[col] = pd.to_numeric(x[col], errors="coerce")
    x = x.dropna(subset=list(required)).sort_values("timestamp").drop_duplicates("timestamp")
    v = x[["open", "high", "low", "close"]].to_numpy(dtype=float)
    valid = (np.isfinite(v).all(axis=1) & (x["open"].to_numpy() > 0) & (x["low"].to_numpy() > 0)
             & (x["high"].to_numpy() >= x[["open", "close", "low"]].max(axis=1).to_numpy())
             & (x["low"].to_numpy() <= x[["open", "close", "high"]].min(axis=1).to_numpy()))
    return x.loc[valid].reset_index(drop=True)


def _hold(reason: str, analysis: dict | None = None) -> PriceActionSignal:
    details = dict(analysis or {})
    details.update({"available": bool(details.get("available", False)), "direction": "HOLD",
                    "setup": details.get("setup", "NONE"),
                    "confidence_basis": "rule_strength_not_win_probability", "note": reason,
                    "expiry_minutes": 1})
    return PriceActionSignal("HOLD", 0.0, reason, "NO_TRADE", "FOREX_STRUCTURE_PA_M1_MTF", details)


def _resample_closed(x: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate M1 candles and remove any higher-timeframe bar not fully closed."""
    if x.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    y = x.set_index("timestamp")[["open", "high", "low", "close"]].resample(
        f"{minutes}min", label="left", closed="left", origin="start_day"
    ).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
    last_m1_end = x.iloc[-1]["timestamp"] + pd.Timedelta(minutes=1)
    y = y.loc[y["timestamp"] + pd.Timedelta(minutes=minutes) <= last_m1_end]
    return y.reset_index(drop=True)


def _swings(x: pd.DataFrame, left: int = 2, right: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs, lows = [], []
    if len(x) < left + right + 3:
        return highs, lows
    h, l = x["high"].to_numpy(float), x["low"].to_numpy(float)
    # Only confirmed pivots: right-hand bars have already closed.
    for i in range(left, len(x) - right):
        if h[i] >= max(h[i-left:i+right+1]) and np.count_nonzero(h[i] == h[i-left:i+right+1]) == 1:
            highs.append((i, float(h[i])))
        if l[i] <= min(l[i-left:i+right+1]) and np.count_nonzero(l[i] == l[i-left:i+right+1]) == 1:
            lows.append((i, float(l[i])))
    return highs, lows


def _structure_bias(x: pd.DataFrame) -> tuple[str, dict]:
    highs, lows = _swings(x)
    info = {"swing_highs": [v for _, v in highs[-3:]], "swing_lows": [v for _, v in lows[-3:]]}
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL", info
    hh = highs[-1][1] > highs[-2][1]
    lh = highs[-1][1] < highs[-2][1]
    hl = lows[-1][1] > lows[-2][1]
    ll = lows[-1][1] < lows[-2][1]
    if hh and hl:
        return "BULLISH", info
    if lh and ll:
        return "BEARISH", info
    return "NEUTRAL", info



def _technical_confirmation_matrix(x: pd.DataFrame) -> dict:
    """Return 127 parameterized technical checks over completed M1 OHLC candles."""
    close, high, low = x["close"], x["high"], x["low"]
    votes: dict[str, int] = {}
    def add(name: str, value) -> None:
        try:
            n=float(value)
            votes[name]=1 if n>0 else -1 if n<0 else 0
        except (TypeError,ValueError):
            votes[name]=0
    for p in (5,8,9,10,12,13,20,21,26,34,50,55,89,100,144,200):
        e=close.ewm(span=p,adjust=False,min_periods=p).mean()
        add(f"Price_vs_EMA_{p}",close.iloc[-1]-e.iloc[-1])
    for p in (5,8,9,10,12,13,20,21,26,34,50,55,89,100,144,200):
        ma=close.rolling(p,min_periods=p).mean()
        add(f"Price_vs_SMA_{p}",close.iloc[-1]-ma.iloc[-1])
    for fast,slow in ((5,10),(8,13),(9,21),(10,20),(12,26),(13,34),(20,50),(21,55),(50,100),(50,200)):
        ef=close.ewm(span=fast,adjust=False,min_periods=fast).mean().iloc[-1]
        es=close.ewm(span=slow,adjust=False,min_periods=slow).mean().iloc[-1]
        add(f"EMA_{fast}_{slow}",ef-es)
    for fast,slow in ((5,10),(8,13),(9,21),(10,20),(12,26),(13,34),(20,50),(21,55),(50,100),(50,200)):
        sf=close.rolling(fast,min_periods=fast).mean().iloc[-1]
        ss=close.rolling(slow,min_periods=slow).mean().iloc[-1]
        add(f"SMA_{fast}_{slow}",sf-ss)
    delta=close.diff()
    gain,loss=delta.clip(lower=0),-delta.clip(upper=0)
    for p in (6,7,9,14,21):
        ag=gain.ewm(alpha=1/p,adjust=False,min_periods=p).mean().iloc[-1]
        al=loss.ewm(alpha=1/p,adjust=False,min_periods=p).mean().iloc[-1]
        rsi=100-100/(1+float(ag)/max(float(al),1e-12))
        for threshold in (45,50,55,60,65):
            add(f"RSI_{p}_{threshold}",rsi-threshold)
    for fast,slow,sig in ((5,13,4),(6,19,5),(8,17,6),(8,21,5),(10,20,7),(12,26,9),(15,30,9),(19,39,9)):
        line=close.ewm(span=fast,adjust=False).mean()-close.ewm(span=slow,adjust=False).mean()
        signal=line.ewm(span=sig,adjust=False).mean()
        add(f"MACD_{fast}_{slow}_{sig}",line.iloc[-1]-signal.iloc[-1])
    for k,d in ((5,3),(7,3),(9,3),(10,3),(14,3),(14,5),(21,5),(8,3)):
        ll,hh=low.rolling(k).min().iloc[-1],high.rolling(k).max().iloc[-1]
        pctk=100*(close.iloc[-1]-ll)/max(float(hh-ll),1e-12)
        add(f"STOCH_{k}_{d}",pctk-50)
    tp=(high+low+close)/3
    for p,level in ((10,-100),(10,100),(14,-100),(14,100),(20,-100),(20,100),(30,-100),(30,100)):
        sma=tp.rolling(p).mean()
        mad=tp.rolling(p).apply(lambda a: np.mean(np.abs(a-np.mean(a))),raw=True)
        cci=(tp-sma)/(0.015*mad.replace(0,np.nan))
        add(f"CCI_{p}_{level}",cci.iloc[-1]-level)
    for p in (3,5,7,9,12,14,20,26):
        add(f"ROC_{p}",(close.iloc[-1]/close.iloc[-1-p]-1)*100 if len(close)>p else 0)
    for p,mult in ((10,2.0),(14,2.0),(20,2.0),(20,2.5),(30,2.0)):
        mid=close.rolling(p).mean().iloc[-1]
        sd=close.rolling(p).std(ddof=0).iloc[-1]
        upper,lower=mid+mult*sd,mid-mult*sd
        add(f"BOLLINGER_{p}_{mult}",close.iloc[-1]-upper if close.iloc[-1]>upper else close.iloc[-1]-lower if close.iloc[-1]<lower else close.iloc[-1]-mid)
    for p in (10,14,20,30,50):
        top,bottom=high.rolling(p).max().iloc[-1],low.rolling(p).min().iloc[-1]
        add(f"DONCHIAN_{p}",close.iloc[-1]-(top+bottom)/2)
    # 4 ADX directional checks using +DI/-DI across common M1 periods.
    up_move=high.diff()
    down_move=-low.diff()
    plus_dm=up_move.where((up_move>down_move)&(up_move>0),0.0)
    minus_dm=down_move.where((down_move>up_move)&(down_move>0),0.0)
    tr=pd.concat([high-low,(high-close.shift(1)).abs(),(low-close.shift(1)).abs()],axis=1).max(axis=1)
    for p in (7,10,14,20):
        atr_p=tr.ewm(alpha=1/p,adjust=False,min_periods=p).mean()
        plus_di=100*plus_dm.ewm(alpha=1/p,adjust=False,min_periods=p).mean()/atr_p.replace(0,np.nan)
        minus_di=100*minus_dm.ewm(alpha=1/p,adjust=False,min_periods=p).mean()/atr_p.replace(0,np.nan)
        add(f"ADX_DI_{p}",plus_di.iloc[-1]-minus_di.iloc[-1])
    # 4 Williams %R checks across different lookbacks.
    for p in (7,10,14,20):
        hh=high.rolling(p).max().iloc[-1]
        ll=low.rolling(p).min().iloc[-1]
        williams=-100*(hh-close.iloc[-1])/max(float(hh-ll),1e-12)
        add(f"WILLIAMS_R_{p}",williams+50)
    items=list(votes.items())
    buy=sum(v==1 for _,v in items); sell=sum(v==-1 for _,v in items); neutral=sum(v==0 for _,v in items)
    return {"total":len(items),"buy":buy,"sell":sell,"neutral":neutral,
            "direction":"BUY" if buy>sell else "SELL" if sell>buy else "NEUTRAL",
            "agreement":round(max(buy,sell)/max(buy+sell,1),4),
            "checks":{n:("BUY" if v==1 else "SELL" if v==-1 else "NEUTRAL") for n,v in items}}

def generate_quotex_price_action_signal(
    candles: pd.DataFrame,
    candles_30m: pd.DataFrame | None = None,
    candles_1h: pd.DataFrame | None = None,
) -> PriceActionSignal:
    """Analyze completed M1 price action with M5/M15 structure and a 1-minute expiry.

    Use completed M1 candles for the setup and aggregate them into M5/M15 context.
    """
    x = _clean(candles)
    if len(x) < 200:
        return _hold("নির্ভরযোগ্য M1 structure ও ১২৭টি confirmation check-এর জন্য কমপক্ষে ২০০টি বন্ধ candle দরকার",
                     {"candle_count": len(x), "available": False, "analysis_timeframe": "1m", "expiry_minutes": 1})
    m1 = x
    m5 = _resample_closed(x, 5)
    m15 = _resample_closed(x, 15)
    bias1, structure1 = _structure_bias(m1)
    bias5, structure5 = _structure_bias(m5)
    bias15, structure15 = _structure_bias(m15)
    last = m1.iloc[-1]
    prior = m1.iloc[-11:-1]
    op, high, low, close = (float(last[k]) for k in ("open", "high", "low", "close"))
    candle_range = max(high - low, 1e-12)
    body = abs(close - op)
    upper_wick = high - max(op, close)
    lower_wick = min(op, close) - low
    close_position = (close - low) / candle_range
    tr = pd.concat([m1["high"] - m1["low"],
                    (m1["high"] - m1["close"].shift(1)).abs(),
                    (m1["low"] - m1["close"].shift(1)).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-2])
    if not np.isfinite(atr) or atr <= 0:
        return _hold("১-মিনিট price range নির্ভরযোগ্য নয়; সিগন্যাল বাদ",
                     {"available": True, "analysis_timeframe": "1m", "expiry_minutes": 1})

    recent_high = float(prior["high"].max())
    recent_low = float(prior["low"].min())
    swing_highs, swing_lows = _swings(m1)
    level_high = swing_highs[-1][1] if swing_highs else recent_high
    level_low = swing_lows[-1][1] if swing_lows else recent_low
    bullish_sweep = low < level_low and close > level_low and close > op and close_position >= 0.65
    bearish_sweep = high > level_high and close < level_high and close < op and close_position <= 0.35
    bullish_bos = close > recent_high and close > op and close_position >= 0.70 and body >= 0.35 * atr
    bearish_bos = close < recent_low and close < op and close_position <= 0.30 and body >= 0.35 * atr
    bullish_rejection = low <= recent_low + 0.12 * atr and close > recent_low and close > op and lower_wick >= max(body, 0.25 * candle_range) and close_position >= 0.65
    bearish_rejection = high >= recent_high - 0.12 * atr and close < recent_high and close < op and upper_wick >= max(body, 0.25 * candle_range) and close_position <= 0.35

    confirmations = _technical_confirmation_matrix(m1)
    details = {
        "available": True, "expiry_minutes": 1, "analysis_timeframe": "1m",
        "technical_confirmation_127": confirmations,
        "candle_count": int(len(x)), "m1_count": int(len(m1)), "m5_count": int(len(m5)), "m15_count": int(len(m15)),
        "latest_closed_candle_time_utc": last["timestamp"].isoformat(),
        "context_timeframes": ["5m", "15m"], "bias_1m": bias1, "bias_5m": bias5, "bias_15m": bias15,
        "structure_1m": structure1, "structure_5m": structure5, "structure_15m": structure15,
        "support": level_low, "resistance": level_high,
        "recent_1m_low": recent_low, "recent_1m_high": recent_high,
        "liquidity_sweep": "bullish" if bullish_sweep else "bearish" if bearish_sweep else None,
        "break_of_structure": "bullish" if bullish_bos else "bearish" if bearish_bos else None,
        "confidence_basis": "rule_strength_not_win_probability",
        "risk_note": "1m price-action setups are probabilistic; no signal guarantees profit.",
    }
    if confirmations["total"] != 127:
        return _hold(f"Indicator calculation incomplete ({confirmations['total']}/127); সিগন্যাল বাদ", details)

    # Keep the 127 checks visible in the Indicators popup, but never use
    # their vote count as a trade trigger. Direction must come from price action.
    details["indicator_vote_summary"] = {
        "source_timeframe": "1m",
        "total_checks": confirmations["total"],
        "buy_votes": confirmations["buy"],
        "sell_votes": confirmations["sell"],
        "neutral_votes": confirmations["neutral"],
        "used_for_signal": False,
        "purpose": "dashboard_confirmation_display_only",
    }

    bullish_setups = [
        ("LIQUIDITY_SWEEP", bullish_sweep),
        ("BREAK_OF_STRUCTURE", bullish_bos),
        ("LEVEL_REJECTION", bullish_rejection),
    ]
    bearish_setups = [
        ("LIQUIDITY_SWEEP", bearish_sweep),
        ("BREAK_OF_STRUCTURE", bearish_bos),
        ("LEVEL_REJECTION", bearish_rejection),
    ]
    bullish_name = next((name for name, active in bullish_setups if active), None)
    bearish_name = next((name for name, active in bearish_setups if active), None)

    if bullish_name and bearish_name:
        return _hold("একই M1 candle-এ BUY ও SELL উভয় price-action setup; direction পরিষ্কার নয়", details)
    if not bullish_name and not bearish_name:
        return _hold("M1 market level-এ নিশ্চিত liquidity sweep, BOS বা rejection পাওয়া যায়নি; অপেক্ষা", details)

    action = "BUY" if bullish_name else "SELL"
    setup = bullish_name or bearish_name
    opposite = "BEARISH" if action == "BUY" else "BULLISH"
    aligned = "BULLISH" if action == "BUY" else "BEARISH"
    reversal = setup == "LIQUIDITY_SWEEP"

    # A reversal sweep may turn the M1 structure; otherwise do not trade
    # directly against a confirmed M1 swing sequence.
    if bias1 == opposite and not reversal:
        return _hold(f"M1 structure {bias1}; {action} setup structure-এর বিপরীতে, sweep নেই", details)
    if bias5 == opposite and bias15 == opposite and not reversal:
        return _hold(f"M5 ও M15 দুটিই {opposite}; M1 {action} setup-এর বিপক্ষে higher-timeframe context", details)

    confidence = 0.62
    confidence += 0.10 if setup == "LIQUIDITY_SWEEP" else 0.08 if setup == "BREAK_OF_STRUCTURE" else 0.06
    confidence += 0.04 if bias1 == aligned else 0.0
    confidence += 0.02 if bias5 == aligned or bias15 == aligned else 0.0
    confidence = min(0.82, confidence)
    details.update({
        "direction": action,
        "setup": setup,
        "confidence": round(confidence, 4),
        "signal_basis": "completed M1 price action: liquidity sweep, break of structure, or level rejection",
        "confirmation": f"{action} from M1 {setup}; M1={bias1}, M5={bias5}, M15={bias15}. 127 checks are display-only.",
        "entry_invalidation_level": level_low if action == "BUY" else level_high,
    })
    reason = f"{action}: M1 {setup} level setup confirmed; M5/M15 context checked; ১ মিনিট expiry."
    return PriceActionSignal(action, confidence, reason,
                             "PRICE_ACTION_BULLISH" if action == "BUY" else "PRICE_ACTION_BEARISH",
                             "FOREX_STRUCTURE_PA_M1_MTF", details)
