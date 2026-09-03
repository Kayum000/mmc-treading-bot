"""Cached Alpha Vantage market-news sentiment for the weekly news panel.

This module intentionally uses one broad NEWS_SENTIMENT request per cache window
instead of one request per pair, so the news panel does not multiply API usage
across the 20 Forex + 10 Crypto markets.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://www.alphavantage.co/query"
CACHE_TTL_SECONDS = 300
API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()

_CURRENCY_NAMES = {
    "USD": "USD", "EUR": "EUR", "GBP": "GBP", "JPY": "JPY",
    "CHF": "CHF", "CAD": "CAD", "AUD": "AUD", "NZD": "NZD",
}
_CRYPTO_NAMES = {"BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "LTC"}
_CACHE = {"data": None, "at": 0.0}
_LOCK = threading.Lock()


def _http_json(params: dict):
    url = f"{API_URL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "mmc-signal-bot/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=12) as response:
        return json.load(response)


def _ticker_sentiment(feed: list[dict]) -> dict[str, dict]:
    """Aggregate article sentiment by currency/crypto ticker."""
    totals = defaultdict(lambda: {"weighted": 0.0, "weight": 0.0, "articles": 0})
    for article in feed:
        article_score = float(article.get("overall_sentiment_score") or 0.0)
        relevance = float(article.get("relevance_score") or 0.5)
        weight = max(0.1, min(relevance, 1.0))
        for item in article.get("ticker_sentiment") or []:
            ticker = str(item.get("ticker") or "").upper()
            if ticker.startswith("FOREX:"):
                key = ticker.split(":", 1)[1]
            elif ticker.startswith("CRYPTO:"):
                key = ticker.split(":", 1)[1]
            else:
                continue
            if key not in _CURRENCY_NAMES and key not in _CRYPTO_NAMES:
                continue
            try:
                score = float(item.get("ticker_sentiment_score"))
            except (TypeError, ValueError):
                score = article_score
            try:
                item_relevance = float(item.get("relevance_score"))
                weight = max(0.1, min(item_relevance, 1.0))
            except (TypeError, ValueError):
                pass
            totals[key]["weighted"] += score * weight
            totals[key]["weight"] += weight
            totals[key]["articles"] += 1

    result = {}
    for key, value in totals.items():
        score = value["weighted"] / value["weight"] if value["weight"] else 0.0
        label = "ইতিবাচক" if score >= 0.15 else "নেতিবাচক" if score <= -0.15 else "নিরপেক্ষ"
        result[key] = {"score": round(score, 3), "label_bn": label, "articles": int(value["articles"])}
    return result


def fetch_news_sentiment(force: bool = False) -> dict:
    """Return cached Alpha Vantage sentiment; never raise for a news-panel failure."""
    if not API_KEY:
        return {"configured": False, "sentiment": {}, "articles": [], "source": "Alpha Vantage"}

    now = time.time()
    with _LOCK:
        if not force and _CACHE["data"] is not None and now - _CACHE["at"] < CACHE_TTL_SECONDS:
            return _CACHE["data"]

    try:
        payload = _http_json({
            "function": "NEWS_SENTIMENT",
            "topics": "economy_macro,economy_monetary,financial_markets,blockchain",
            "sort": "LATEST",
            "limit": 50,
            "apikey": API_KEY,
        })
        if not isinstance(payload, dict) or "feed" not in payload:
            data = {"configured": True, "sentiment": {}, "articles": [], "source": "Alpha Vantage", "error": payload.get("Note") or payload.get("Information") if isinstance(payload, dict) else "Invalid response"}
        else:
            feed = [x for x in payload.get("feed", []) if isinstance(x, dict)]
            articles = []
            for article in feed[:12]:
                articles.append({
                    "title": str(article.get("title") or "").strip(),
                    "url": str(article.get("url") or "").strip(),
                    "published_at": str(article.get("time_published") or "").strip(),
                    "sentiment_label": str(article.get("overall_sentiment_label") or "Neutral").strip(),
                    "sentiment_score": article.get("overall_sentiment_score"),
                })
            data = {
                "configured": True,
                "sentiment": _ticker_sentiment(feed),
                "articles": articles,
                "source": "Alpha Vantage NEWS_SENTIMENT",
            }
        with _LOCK:
            _CACHE["data"] = data
            _CACHE["at"] = now
        return data
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        with _LOCK:
            return _CACHE["data"] or {"configured": True, "sentiment": {}, "articles": [], "source": "Alpha Vantage", "error": "News feed unavailable"}


def pair_sentiment(pair: str, market_mode: str, data: dict | None = None) -> dict:
    """Summarize Alpha Vantage sentiment relevant to one pair."""
    data = data or fetch_news_sentiment()
    sentiment = data.get("sentiment", {})
    if market_mode == "crypto":
        base = pair.upper().split("/", 1)[0]
        keys = [base, "USD"]
    else:
        keys = [part for part in pair.upper().split("/") if part]
    matches = [sentiment[k] | {"ticker": k} for k in keys if k in sentiment]
    if not matches:
        return {"available": False, "label_bn": "暂无足够相关新闻情绪数据", "score": 0.0, "articles": 0, "details": []}
    score = sum(x["score"] for x in matches) / len(matches)
    label = "ইতিবাচক" if score >= 0.15 else "নেতিবাচক" if score <= -0.15 else "নিরপেক্ষ"
    return {"available": True, "label_bn": label, "score": round(score, 3), "articles": sum(x["articles"] for x in matches), "details": matches}
