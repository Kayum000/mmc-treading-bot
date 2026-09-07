"""Canonical Mirror MMC with 22 supporting Market Maker Cycle votes.
The Mirror MMC remains the only final directional gate; concept votes never flip it.
No EMA/RSI/MACD/MTF.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import time
import pandas as pd
from config import CONFIG

@dataclass(frozen=True)
class Signal:
    action: str
    buy_score: int
    sell_score: int
    reason: str

def _valid(df, n): return df is not None and not df.empty and len(df) >= n
def _rng(r): return max(float(r['high'])-float(r['low']),1e-12)
def _body(r): return abs(float(r['close'])-float(r['open']))
def _ratio(r): return _body(r)/_rng(r)
def _dir(r):
    return 'bullish' if float(r['close'])>float(r['open']) else 'bearish' if float(r['close'])<float(r['open']) else 'doji'
def _atr(df,n=10): return max(float((df['high'].astype(float)-df['low'].astype(float)).tail(n).median()),1e-12)
def _near(a,b,t): return abs(float(a)-float(b))<=float(t)

def market_structure(df, lookback=3):
    if not _valid(df,lookback+2): return 'neutral'
    p=df.iloc[-lookback-1:-1]; c=float(df.iloc[-1]['close'])
    if c>float(p['high'].max()): return 'bullish_bos'
    if c<float(p['low'].min()): return 'bearish_bos'
    return 'neutral'

def liquidity_sweep(df,lookback=10):
    if not _valid(df,lookback+1): return 'none'
    p=df.iloc[-lookback-1:-1]; r=df.iloc[-1]
    sell=float(r['high'])>float(p['high'].max()) and float(r['close'])<float(p['high'].max())
    buy=float(r['low'])<float(p['low'].min()) and float(r['close'])>float(p['low'].min())
    if sell and not buy:return 'sell_side_rejection'
    if buy and not sell:return 'buy_side_rejection'
    return 'none'

def displacement(df):
    if not _valid(df,3): return 'none'
    a,b=df.iloc[-2],df.iloc[-1]
    if _ratio(b)<.65 or _rng(b)<_rng(a)*1.10:return 'none'
    return _dir(b) if _dir(b)!='doji' else 'none'

def _swings(p):
    hi=[];lo=[]
    for i in range(2,len(p)-2):
        w=p.iloc[i-2:i+3]; h=float(p.iloc[i]['high']); l=float(p.iloc[i]['low'])
        if h>=float(w['high'].max()):hi.append(h)
        if l<=float(w['low'].min()):lo.append(l)
    return hi,lo

def _clusters(vals,t):
    out=[]
    for v in sorted(float(x) for x in vals):
        if not out or abs(v-out[-1]['price'])>t:out.append({'price':v,'touches':1})
        else:
            c=out[-1]; c['price']=(c['price']*c['touches']+v)/(c['touches']+1);c['touches']+=1
    return out

def _mirror(df,side,lookback=20):
    if not _valid(df,lookback+7):return None
    p=df.iloc[-lookback-1:-1].copy().reset_index(drop=True); t=max(_atr(p)*.08,1e-12)
    hs,ls=_swings(p); rc=_clusters(hs,t); sc=_clusters(ls,t); last=float(p.iloc[-1]['close']); cs=[]
    if side=='SELL':
        for zc in rc:
            z=zc['price']
            if zc['touches']<1 or z<last-t:continue
            for i in range(2,len(p)-3):
                o=float(p.iloc[i]['low']); w=p.iloc[i-2:i+3]
                if o>float(w['low'].min())+t:continue
                if not any(c['touches']>=1 and _near(o,c['price'],t) for c in sc):continue
                d=z-o; f=p.iloc[i+1:]
                if d<=t*3 or f.empty:continue
                if not ((f['close'].astype(float)>f['open'].astype(float)) & (f.apply(_ratio,axis=1)>=.55)).any():continue
                if float(f['high'].max())<z-t:continue
                cs.append({'side':'SELL','origin':o,'zone':z,'distance':d,'equilibrium':o+d*.5,'mirror_target':z-d,'tolerance':t,'zone_touches':zc['touches'],'structure_confluence':True,'origin_index':i})
    else:
        for zc in sc:
            z=zc['price']
            if zc['touches']<1 or z>last+t:continue
            for i in range(2,len(p)-3):
                o=float(p.iloc[i]['high']); w=p.iloc[i-2:i+3]
                if o<float(w['high'].max())-t:continue
                if not any(c['touches']>=1 and _near(o,c['price'],t) for c in rc):continue
                d=o-z; f=p.iloc[i+1:]
                if d<=t*3 or f.empty:continue
                if not ((f['close'].astype(float)<f['open'].astype(float)) & (f.apply(_ratio,axis=1)>=.55)).any():continue
                if float(f['low'].min())>z+t:continue
                cs.append({'side':'BUY','origin':o,'zone':z,'distance':d,'equilibrium':o-d*.5,'mirror_target':z+d,'tolerance':t,'zone_touches':zc['touches'],'structure_confluence':True,'origin_index':i})
    return max(cs,key=lambda x:(x['origin_index'],x['zone_touches'])) if cs else None

def get_mirror_projection(df,side,lookback=20): return _mirror(df,str(side).upper(),lookback)

def level_for_side(df, side, lookback=20):
    """Return the canonical Mirror MMC level for BUY/SELL as (type, price)."""
    side=str(side).upper()
    if side not in {'BUY','SELL'}: return None
    mirror=get_mirror_projection(df,side,lookback)
    if not mirror: return None
    level_type='supply-origin' if side=='SELL' else 'demand-origin'
    return level_type, float(mirror['zone'])

def strong_level_rejection(df,lookback=20):
    if df is None or df.empty:return 'none'
    r=df.iloc[-1]; hi,lo=float(r['high']),float(r['low']);o,c=float(r['open']),float(r['close']);rg=_rng(r);b=abs(c-o);up=hi-max(o,c);dn=min(o,c)-lo;s=liquidity_sweep(df,min(10,len(df)-1));imp=displacement(df)
    sm=get_mirror_projection(df,'SELL',lookback);bm=get_mirror_projection(df,'BUY',lookback)
    sell=bool(sm) and hi>=sm['zone']-sm['tolerance'] and c<sm['zone'] and c<=lo+rg*.55 and up>=max(b*1.20,rg*.25) and (s=='sell_side_rejection' or imp=='bearish')
    buy=bool(bm) and lo<=bm['zone']+bm['tolerance'] and c>bm['zone'] and c>=lo+rg*.45 and dn>=max(b*1.20,rg*.25) and (s=='buy_side_rejection' or imp=='bullish')
    return 'strong_resistance_rejection' if sell and not buy else 'strong_support_rejection' if buy and not sell else 'none'

def _gen_votes(df,side):
    side=str(side).upper(); want='bullish' if side=='BUY' else 'bearish'; sweep=liquidity_sweep(df,10); struct=market_structure(df,CONFIG.swing_lookback); imp=displacement(df); r=df.iloc[-1]; p=df.iloc[:-1]
    t=max(_atr(p)*.12,1e-12); recent=df.tail(12); hs,ls=_swings(recent); clusters=_clusters(ls if side=='BUY' else hs,t)
    liquidity_gen=any(x['touches']>=2 for x in clusters)
    hi=float(recent['high'].max());lo=float(recent['low'].min());mid=lo+(hi-lo)*.5;cl=float(r['close'])
    premium_discount=cl<=mid if side=='BUY' else cl>=mid
    induce=(float(r['low'])<float(recent.iloc[:-1]['low'].min())-t and cl>float(recent.iloc[:-1]['low'].min())) if side=='BUY' else (float(r['high'])>float(recent.iloc[:-1]['high'].max())+t and cl<float(recent.iloc[:-1]['high'].max()))
    engineered=liquidity_gen
    ob=_order_block(df,side);ifc=_ifc(df,side);fvg=_fvg(df,side);ifvg=_ifvg(df,side);void=_void(df,side);mit=_mitigation(df,side);breaker=_breaker(df,side);rej=_rejection(df,side);prop=_propulsion(df,side);ote=_ote(df,side);zone=_kill_zone(df);dist=_distribution(df,side)
    return {'accumulation':liquidity_gen and _range_consolidating(recent),'liquidity_generation':liquidity_gen,'premium_discount':premium_discount,'inducement':induce,'engineering_liquidity':engineered,'judas_stop_hunt':induce or sweep==('buy_side_rejection' if side=='BUY' else 'sell_side_rejection'),'liquidity_sweep':sweep==('buy_side_rejection' if side=='BUY' else 'sell_side_rejection'),'order_block_activation':ob,'ifc':ifc,'displacement':imp==want,'mss_choch':_mss(df,side),'bos':struct==('bullish_bos' if side=='BUY' else 'bearish_bos'),'fvg':fvg,'ifvg':ifvg,'liquidity_void':void,'mitigation':mit,'breaker_block':breaker,'rejection_block':rej,'propulsion_block':prop,'ote':ote,'kill_zone':zone,'distribution_completion':dist}

def _range_consolidating(df):
    if len(df)<5:return False
    rs=df['high'].astype(float)-df['low'].astype(float);return float(rs.tail(5).median())<=max(float(rs.median())*1.35,1e-12)

def _mss(df,side):
    if not _valid(df,7):return False
    p=df.iloc[-6:-1];c=float(df.iloc[-1]['close']);return c>float(p['high'].max()) if side=='BUY' else c<float(p['low'].min())

def _order_block(df,side):
    if not _valid(df,5):return False
    p=df.iloc[-4:-1];r=df.iloc[-1]
    if side=='BUY':
        x=p[p['close'].astype(float)<p['open'].astype(float)];return not x.empty and float(r['close'])>float(x.iloc[-1]['high'])
    x=p[p['close'].astype(float)>p['open'].astype(float)];return not x.empty and float(r['close'])<float(x.iloc[-1]['low'])

def _ifc(df,side):
    if not _valid(df,5):return False
    x=df.iloc[-4:];opp='bearish' if side=='BUY' else 'bullish';return any(_dir(r)==opp and _ratio(r)>=.55 for _,r in x.iterrows()) and _dir(df.iloc[-1])==('bullish' if side=='BUY' else 'bearish')

def _fvg(df,side):
    if not _valid(df,3):return False
    a,c=df.iloc[-3],df.iloc[-1]
    return float(c['low'])>float(a['high']) if side=='BUY' else float(c['high'])<float(a['low'])

def _ifvg(df,side):
    if not _valid(df,5):return False
    x=df.tail(5).reset_index(drop=True)
    for i in range(2,4):
        a,c=x.iloc[i-2],x.iloc[i]
        if side=='BUY' and float(c['low'])>float(a['high']) and float(x.iloc[i+1]['low'])<float(a['high']):return True
        if side=='SELL' and float(c['high'])<float(a['low']) and float(x.iloc[i+1]['high'])>float(a['low']):return True
    return False

def _void(df,side):
    if not _valid(df,5):return False
    r=df.iloc[-1];return _rng(r)>=_atr(df.iloc[:-1])*2 and _ratio(r)>=.75 and _dir(r)==('bullish' if side=='BUY' else 'bearish')

def _mitigation(df,side):
    if not _valid(df,7):return False
    p=df.iloc[-7:-1];r=df.iloc[-1]
    x=p[p['close'].astype(float)<p['open'].astype(float)] if side=='BUY' else p[p['close'].astype(float)>p['open'].astype(float)]
    if x.empty:return False
    level=float(x.iloc[-1]['high'] if side=='BUY' else x.iloc[-1]['low']);return (float(r['low'])<=level and float(r['close'])>level) if side=='BUY' else (float(r['high'])>=level and float(r['close'])<level)

def _breaker(df,side):
    if not _valid(df,6):return False
    r=df.iloc[-1];p=df.iloc[-5:-1];return any((float(r['low'])<=float(x['low']) and _dir(r)=='bullish') for _,x in p.iterrows()) if side=='BUY' else any((float(r['high'])>=float(x['high']) and _dir(r)=='bearish') for _,x in p.iterrows())

def _rejection(df,side):
    if df is None or df.empty:return False
    r=df.iloc[-1];b=_body(r);rg=_rng(r);up=float(r['high'])-max(float(r['open']),float(r['close']));dn=min(float(r['open']),float(r['close']))-float(r['low'])
    return (dn>=max(b*1.5,rg*.35) and _dir(r)=='bullish') if side=='BUY' else (up>=max(b*1.5,rg*.35) and _dir(r)=='bearish')

def _propulsion(df,side):
    if not _valid(df,5):return False
    x=df.tail(4);want='bullish' if side=='BUY' else 'bearish';return sum(_dir(r)==want for _,r in x.iterrows())>=3 and _ratio(df.iloc[-1])>=.60

def _ote(df,side):
    if not _valid(df,8):return False
    x=df.tail(12);hi=float(x['high'].max());lo=float(x['low'].min());span=max(hi-lo,1e-12);c=float(x.iloc[-1]['close']);r=(hi-c)/span if side=='BUY' else (c-lo)/span;return .62<=r<=.79

def _kill_zone(df):
    try:
        t=pd.to_datetime(df.index[-1],utc=True).time();return time(7)<=t<=time(10) or time(13)<=t<=time(17)
    except Exception:return False

def _distribution(df,side):
    if not _valid(df,8):return False
    x=df.tail(8);hi=float(x['high'].max());lo=float(x['low'].min());c=float(x.iloc[-1]['close']);span=max(hi-lo,1e-12);return (c-lo)/span>=.90 if side=='BUY' else (hi-c)/span>=.90

def concept_scores(df,mirror=None):
    bv=_gen_votes(df,'BUY');sv=_gen_votes(df,'SELL');return sum(bv.values()),sum(sv.values()),{'BUY':bv,'SELL':sv}

def _relaxed_confirmation(df, side, lookback, score, opposite_score):
    """Allow valid Mirror MMC entries when the full rejection pattern is absent.
    The Mirror setup remains mandatory, but the old proximity/score gate was too
    restrictive and could suppress otherwise confirmed entries.
    """
    side=str(side).upper()
    mirror=get_mirror_projection(df,side,lookback)
    if not mirror:
        return False
    close=float(df.iloc[-1]['close'])
    proximity=max(float(mirror['tolerance'])*4.0, _atr(df)*0.60)
    near_zone=abs(close-float(mirror['zone']))<=proximity
    if not near_zone:
        return False
    want='buy_side_rejection' if side=='BUY' else 'sell_side_rejection'
    want_imp='bullish' if side=='BUY' else 'bearish'
    sweep=liquidity_sweep(df,10)==want
    imp=displacement(df)==want_imp
    rejection=_rejection(df,side)
    structure=market_structure(df,CONFIG.swing_lookback)==('bullish_bos' if side=='BUY' else 'bearish_bos')
    candle=_dir(df.iloc[-1])==want_imp
    margin=score-opposite_score
    return margin>=1 and score>=4 and (sweep or imp or rejection or structure or candle)

def final_confirmation(df,side,lookback=20):
    side=str(side).lower()
    mirror=get_mirror_projection(df,side.upper(),lookback)
    if not mirror:
        return False
    r=strong_level_rejection(df,lookback)
    expected='strong_support_rejection' if side=='buy' else 'strong_resistance_rejection'
    confirm=liquidity_sweep(df,10)==('buy_side_rejection' if side=='buy' else 'sell_side_rejection') or displacement(df)==('bullish' if side=='buy' else 'bearish')
    if r==expected and confirm:
        return True
    bv,sv,_=concept_scores(df)
    score=bv if side=='buy' else sv
    opposite=sv if side=='buy' else bv
    return _relaxed_confirmation(df,side,lookback,score,opposite)

def generate_signal(df):
    minimum=max(CONFIG.sweep_lookback+1,CONFIG.level_lookback+5,27)
    if not _valid(df,minimum):return Signal('NO_TRADE',0,0,'পরিষ্কার MMC যাচাইয়ের জন্য পর্যাপ্ত বন্ধ ১ মিনিটের ক্যান্ডেল নেই।')
    buy_m=get_mirror_projection(df,'BUY',CONFIG.level_lookback);sell_m=get_mirror_projection(df,'SELL',CONFIG.level_lookback);st=market_structure(df,CONFIG.swing_lookback);sw=liquidity_sweep(df,CONFIG.sweep_lookback);imp=displacement(df);bv,sv,_=concept_scores(df)
    buy_ok=final_confirmation(df,'buy',CONFIG.level_lookback);sell_ok=final_confirmation(df,'sell',CONFIG.level_lookback)
    if buy_ok and not sell_ok:
        return Signal('BUY',bv,sv,f'Mirror MMC BUY confirmed; supporting concept votes {bv}/22 vs {sv}/22. Final direction is controlled only by the main Mirror MMC.')
    if sell_ok and not buy_ok:
        return Signal('SELL',bv,sv,f'Mirror MMC SELL confirmed; supporting concept votes {bv}/22 vs {sv}/22. Final direction is controlled only by the main Mirror MMC.')
    if buy_m and sell_m and st=='neutral' and sw=='none' and imp=='none':
        return Signal('NO_TRADE',bv,sv,'একই সময়ে দুই দিকের Mirror MMC setup পরিষ্কার নয়; তাই কোনো Entry নেই।')
    return Signal('NO_TRADE',bv,sv,f'Valid Supply/Demand origin → dynamic impulse measure → 50% equilibrium → AB=CD mirror → structure confluence → rejection → confirmation একসঙ্গে তৈরি হয়নি; তাই signal নেই। Supporting votes: BUY {bv}/22, SELL {sv}/22.')