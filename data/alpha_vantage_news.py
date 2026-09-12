"""Cached Alpha Vantage market-news sentiment for Forex news.

One cached NEWS_SENTIMENT request is used for the real Forex news panel.
Quotex OTC does not use economic-news filtering in the signal path.
"""
from __future__ import annotations
import json, os, threading, time
from collections import defaultdict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
API_URL="https://www.alphavantage.co/query"; CACHE_TTL_SECONDS=300; API_KEY=os.getenv("ALPHA_VANTAGE_API_KEY","").strip()
_CURRENCY_NAMES={"USD","EUR","GBP","JPY","CHF","CAD","AUD","NZD"}; _CACHE={"data":None,"at":0.0}; _LOCK=threading.Lock()
def _http_json(params):
    req=Request(f"{API_URL}?{urlencode(params)}",headers={"User-Agent":"mmc-signal-bot/1.0","Accept":"application/json"})
    with urlopen(req,timeout=12) as response:return json.load(response)
def _ticker_sentiment(feed):
    totals=defaultdict(lambda:{"weighted":0.0,"weight":0.0,"articles":0})
    for article in feed:
        article_score=float(article.get("overall_sentiment_score") or 0.0)
        for item in article.get("ticker_sentiment") or []:
            ticker=str(item.get("ticker") or "").upper()
            if not ticker.startswith("FOREX:"):continue
            key=ticker.split(":",1)[1]
            if key not in _CURRENCY_NAMES:continue
            try:score=float(item.get("ticker_sentiment_score"))
            except (TypeError,ValueError):score=article_score
            try:relevance=float(item.get("relevance_score"))
            except (TypeError,ValueError):relevance=0.5
            weight=max(0.1,min(relevance,1.0)); totals[key]["weighted"]+=score*weight; totals[key]["weight"]+=weight; totals[key]["articles"]+=1
    result={}
    for key,value in totals.items():
        score=value["weighted"]/value["weight"] if value["weight"] else 0.0; label="ইতিবাচক" if score>=0.15 else "নেতিবাচক" if score<=-0.15 else "নিরপেক্ষ"
        result[key]={"score":round(score,3),"label_bn":label,"articles":int(value["articles"])}
    return result
def fetch_news_sentiment(force=False):
    if not API_KEY:return {"configured":False,"sentiment":{},"articles":[],"source":"Alpha Vantage"}
    now=time.time()
    with _LOCK:
        if not force and _CACHE["data"] is not None and now-_CACHE["at"]<CACHE_TTL_SECONDS:return _CACHE["data"]
    try:
        payload=_http_json({"function":"NEWS_SENTIMENT","topics":"economy_macro,economy_monetary,financial_markets","sort":"LATEST","limit":50,"apikey":API_KEY})
        if not isinstance(payload,dict) or "feed" not in payload:
            error=(payload.get("Note") or payload.get("Information")) if isinstance(payload,dict) else "Invalid response"; data={"configured":True,"sentiment":{},"articles":[],"source":"Alpha Vantage","error":error}
        else:
            feed=[x for x in payload.get("feed",[]) if isinstance(x,dict)]; articles=[{"title":str(a.get("title") or "").strip(),"url":str(a.get("url") or "").strip(),"published_at":str(a.get("time_published") or "").strip(),"sentiment_label":str(a.get("overall_sentiment_label") or "Neutral").strip(),"sentiment_score":a.get("overall_sentiment_score")} for a in feed[:12]]
            data={"configured":True,"sentiment":_ticker_sentiment(feed),"articles":articles,"source":"Alpha Vantage NEWS_SENTIMENT"}
        with _LOCK:_CACHE["data"],_CACHE["at"]=data,now
        return data
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,json.JSONDecodeError):
        with _LOCK:return _CACHE["data"] or {"configured":True,"sentiment":{},"articles":[],"source":"Alpha Vantage","error":"News feed unavailable"}
def pair_sentiment(pair,data=None):
    data=data or fetch_news_sentiment(); sentiment=data.get("sentiment",{}); keys=[part for part in pair.upper().split("/") if part]; matches=[sentiment[k]|{"ticker":k} for k in keys if k in sentiment]
    if not matches:return {"available":False,"label_bn":"暂无足够相关新闻情绪数据","score":0.0,"articles":0,"details":[]}
    score=sum(x["score"] for x in matches)/len(matches); label="ইতিবাচক" if score>=0.15 else "নেতিবাচক" if score<=-0.15 else "নিরপেক্ষ"
    return {"available":True,"label_bn":label,"score":round(score,3),"articles":sum(x["articles"] for x in matches),"details":matches}
