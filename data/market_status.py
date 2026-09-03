"""Market session/status helper for the web UI.

This module uses the current UTC clock and the cached scheduled-news calendar.
It deliberately does not call Alpha Vantage or any candle/market-data API.
"""
from __future__ import annotations

from datetime import datetime, timezone

from data.news_events import get_weekly_news_events_for_pair


def _session_info(now_utc: datetime):
    """Return the major forex session state using UTC hours."""
    hour = now_utc.hour + now_utc.minute / 60.0

    if 12 <= hour < 16:
        return "লন্ডন + নিউ ইয়র্ক ওভারল্যাপ", "HIGH", "সেরা উইন্ডো: ১৮:০০–২২:০০ (বাংলাদেশ সময়)"
    if 7 <= hour < 12:
        return "লন্ডন সেশন", "HIGH", "ভালো উইন্ডো: ১৩:০০–১৮:০০ (বাংলাদেশ সময়)"
    if 16 <= hour < 21:
        return "নিউ ইয়র্ক সেশন", "HIGH", "ভালো উইন্ডো: ২২:০০–০৩:০০ (বাংলাদেশ সময়)"
    if 0 <= hour < 7:
        return "এশিয়া সেশন", "MEDIUM", "এশিয়া সেশন: মুভমেন্ট তুলনামূলক কম হতে পারে"
    return "সেশন ট্রানজিশন", "LOW", "বড় সেটআপ না হলে অপেক্ষা করা ভালো"


def _next_news(events, now_utc):
    future = []
    for event in events or []:
        try:
            raw = str(event.get("event_time_utc", "")).replace("Z", "+00:00")
            event_time = datetime.fromisoformat(raw)
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
            event_time = event_time.astimezone(timezone.utc)
            if event_time >= now_utc:
                future.append((event_time, event))
        except (TypeError, ValueError):
            continue
    return min(future, key=lambda item: item[0]) if future else (None, None)


def get_market_status(mode: str, pair: str, real_pairs, crypto_pairs):
    """Build the left-side status panel payload without Alpha Vantage."""
    now = datetime.now(timezone.utc)
    session_name, activity, window = _session_info(now)

    news = {}
    try:
        news = get_weekly_news_events_for_pair(mode, real_pairs, crypto_pairs, pair) or {}
    except Exception:
        news = {}

    event_time, event = _next_news(news.get("events", []), now)
    news_risk = "LOW"
    news_risk_bn = "কোনো কাছের high-impact নিউজ নেই"
    minutes = None
    minutes_float = float("inf")
    if event_time and event:
        minutes_float = max(0.0, (event_time - now).total_seconds() / 60.0)
        minutes = round(minutes_float, 1)
        impact = str(event.get("impact", "low")).lower()
        if impact == "high" and minutes_float <= 5:
            news_risk = "HIGH"
            news_risk_bn = f"🚨 {event.get('currency_bn', '')} — {event.get('title_bn', '')} | আর {minutes:g} মিনিট"
        elif impact == "high":
            news_risk = "MEDIUM"
            news_risk_bn = f"High-impact নিউজ {minutes:g} মিনিট পরে"
        elif minutes_float <= 15:
            news_risk = "MEDIUM"
            news_risk_bn = f"গুরুত্বপূর্ণ নিউজ {minutes:g} মিনিট পরে"
        else:
            news_risk_bn = f"পরবর্তী নিউজ {minutes:g} মিনিট পরে"

    direction_needed = bool(
        event and str(event.get("impact", "")).lower() == "high" and minutes_float <= 5
    )

    if news_risk == "HIGH":
        recommendation = "AVOID — নিউজ রিলিজের আগে ট্রেড নয়"
        recommendation_bn = "🚫 এখন ট্রেড এড়িয়ে চলো"
    elif activity == "HIGH" and news_risk != "MEDIUM":
        recommendation = "TRADE WINDOW — সেটআপ মিললে দেখুন"
        recommendation_bn = "🟢 ট্রেডিং উইন্ডো সক্রিয় — সেটআপ মিললে ট্রেড"
    elif activity == "MEDIUM" and news_risk == "LOW":
        recommendation = "WAIT — শক্ত সেটআপের অপেক্ষা"
        recommendation_bn = "🟡 অপেক্ষা — শক্ত সেটআপ না আসা পর্যন্ত"
    else:
        recommendation = "WAIT — পরিস্থিতি পরিষ্কার হওয়া পর্যন্ত"
        recommendation_bn = "🟡 অপেক্ষা করা ভালো"

    return {
        "ok": True,
        "pair": pair,
        "market_mode": mode,
        "checked_at_utc": now.isoformat(),
        "session": session_name,
        "activity": activity,
        "activity_bn": {"HIGH": "উচ্চ", "MEDIUM": "মাঝারি", "LOW": "কম"}[activity],
        "best_window_bn": window,
        "news_risk": news_risk,
        "news_risk_bn": news_risk_bn,
        "next_news_minutes": minutes,
        "next_news_time_utc": event_time.isoformat() if event_time else None,
        "next_news_title_bn": event.get("title_bn") if event else None,
        "next_news_currency_bn": event.get("currency_bn") if event else None,
        "direction_needed": direction_needed,
        "recommendation": recommendation,
        "recommendation_bn": recommendation_bn,
    }
