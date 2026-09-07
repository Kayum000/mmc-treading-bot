"""Market session/status helper for the web UI.

Uses the cached scheduled-news calendar and cached Alpha Vantage sentiment.
The Pre-News Direction is calculated from the nearest upcoming event and its
currency-specific sentiment, so the Market Status panel can show BUY/SELL
when a usable sentiment signal exists.
"""
from __future__ import annotations

from datetime import datetime, timezone

from data.news_events import get_weekly_news_events_for_pair
from data.all_news_events import get_all_news_events
from data.alpha_vantage_news import fetch_news_sentiment


def _session_info(now_utc: datetime):
    """Return the major forex session state using UTC hours."""
    hour = now_utc.hour + now_utc.minute / 60.0
    if 12 <= hour < 16:
        return "London + New York Overlap", "HIGH", "Best window: 18:00–22:00 (Bangladesh Time)"
    if 7 <= hour < 12:
        return "London Session", "HIGH", "Good window: 13:00–18:00 (Bangladesh Time)"
    if 16 <= hour < 21:
        return "New York Session", "HIGH", "Good window: 22:00–03:00 (Bangladesh Time)"
    if 0 <= hour < 7:
        return "Asia Session", "MEDIUM", "Asia session: movement may be relatively lower"
    return "Session Transition", "LOW", "Wait unless a strong setup appears"


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


def _pair_matches_currency(pair: str, currency: str) -> bool:
    parts = str(pair or "").upper().split("/", 1)
    return len(parts) == 2 and str(currency or "").upper() in parts


def _pre_news_direction_for_event(event: dict, real_pairs: list[str], crypto_pairs: list[str]) -> dict:
    """Calculate BUY/SELL from the nearest event's currency-specific sentiment."""
    if not event:
        return {"available": False}

    currency = str(event.get("currency") or "").upper()
    event_time = str(event.get("event_time_utc") or "")
    if not currency or not event_time:
        return {"available": False}

    affected_pairs = [p for p in real_pairs if _pair_matches_currency(p, currency)]
    if not affected_pairs:
        return {"available": False, "event_time_utc": event_time}

    target_pair = affected_pairs[0]
    try:
        news_data = fetch_news_sentiment()
        ticker = (news_data.get("sentiment") or {}).get(currency) or {}
        score = float(ticker.get("score") or 0.0)
        articles = int(ticker.get("articles") or 0)
    except Exception:
        score = 0.0
        articles = 0

    base, quote = target_pair.upper().split("/", 1)
    if abs(score) < 0.15:
        direction = "WAIT"
    elif currency == base:
        direction = "BUY" if score > 0 else "SELL"
    elif currency == quote:
        direction = "SELL" if score > 0 else "BUY"
    else:
        direction = "WAIT"

    confidence = round(max(35.0, min(95.0, 50.0 + min(abs(score), 1.0) * 45.0)))
    if direction == "WAIT":
        confidence = round(max(35.0, 50.0 - min(abs(score), 1.0) * 25.0))

    return {
        "available": True,
        "market": target_pair,
        "event_time_utc": event_time,
        "currency": currency,
        "direction": direction,
        "confidence_pct": confidence,
        "sentiment_score": round(score, 3),
        "articles": articles,
        "source": "Alpha Vantage NEWS_SENTIMENT (cached)",
    }


def _global_pre_news_direction(mode: str, real_pairs: list[str], crypto_pairs: list[str]) -> dict:
    """Return direction for the single nearest upcoming real-market event."""
    if mode != "real":
        return {"available": False, "reason": "Pre-News Direction is currently supported for real-market news."}

    try:
        all_news = get_all_news_events(mode, real_pairs, crypto_pairs) or {}
        _, event = _next_news(all_news.get("events", []), datetime.now(timezone.utc))
        if not event:
            return {"available": False, "reason": "No upcoming news event is available."}
        return _pre_news_direction_for_event(event, real_pairs, crypto_pairs)
    except Exception as exc:
        return {"available": False, "reason": str(exc)}


def get_market_status(mode: str, pair: str, real_pairs, crypto_pairs):
    """Build the left-side status panel payload without market-data API calls."""
    now = datetime.now(timezone.utc)
    session_name, activity, window = _session_info(now)

    news = {}
    try:
        news = get_weekly_news_events_for_pair(mode, real_pairs, crypto_pairs, pair) or {}
    except Exception:
        news = {}

    event_time, event = _next_news(news.get("events", []), now)
    news_risk = "LOW"
    news_risk_text = "No nearby high-impact news"
    minutes = None
    minutes_float = float("inf")
    if event_time and event:
        minutes_float = max(0.0, (event_time - now).total_seconds() / 60.0)
        minutes = round(minutes_float, 1)
        impact = str(event.get("impact", "low")).lower()
        title = str(event.get("title") or event.get("title_bn") or "Scheduled News")
        currency = str(event.get("currency") or "").upper()
        if impact == "high" and minutes_float <= 5:
            news_risk = "HIGH"
            news_risk_text = f"🚨 {currency} — {title} | In {minutes:g} minutes"
        elif impact == "high":
            news_risk = "MEDIUM"
            news_risk_text = f"High-impact news in {minutes:g} minutes"
        elif minutes_float <= 15:
            news_risk = "MEDIUM"
            news_risk_text = f"Important news in {minutes:g} minutes"
        else:
            news_risk_text = f"Next news in {minutes:g} minutes"

    direction_needed = bool(event and str(event.get("impact", "")).lower() == "high" and minutes_float <= 5)

    if news_risk == "HIGH":
        recommendation = "AVOID — No trade before the news release"
    elif activity == "HIGH" and news_risk != "MEDIUM":
        recommendation = "TRADE WINDOW — Trade only when setup confirms"
    elif activity == "MEDIUM" and news_risk == "LOW":
        recommendation = "WAIT — Strong setup required"
    else:
        recommendation = "WAIT — Wait for clearer conditions"

    return {
        "ok": True,
        "pair": pair,
        "market_mode": mode,
        "checked_at_utc": now.isoformat(),
        "session": session_name,
        "activity": activity,
        "activity_bn": activity,
        "best_window_bn": window,
        "news_risk": news_risk,
        "news_risk_bn": news_risk_text,
        "next_news_minutes": minutes,
        "next_news_time_utc": event_time.isoformat() if event_time else None,
        "next_news_title_bn": (event.get("title") or event.get("title_bn")) if event else None,
        "next_news_currency_bn": event.get("currency") if event else None,
        "direction_needed": direction_needed,
        "pre_news_direction": _global_pre_news_direction(mode, real_pairs, crypto_pairs),
        "recommendation": recommendation,
        "recommendation_bn": recommendation,
    }
