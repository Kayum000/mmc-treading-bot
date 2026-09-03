"""Scheduled market-news calendar, Alpha Vantage sentiment, and five-minute alerts."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from data.alpha_vantage_news import fetch_news_sentiment, pair_sentiment

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
# Keep the application cache short because this endpoint can change during the day.
# The request itself is also cache-busted once per minute below so an upstream CDN
# cannot keep returning an older weekly calendar indefinitely.
CACHE_TTL_SECONDS = 60

_CACHE = {"events": None, "at": 0.0}
_LOCK = threading.Lock()

CURRENCY_NAMES = {
    "USD": "মার্কিন ডলার", "EUR": "ইউরো", "GBP": "ব্রিটিশ পাউন্ড",
    "JPY": "জাপানি ইয়েন", "CHF": "সুইস ফ্রাঁ", "CAD": "কানাডিয়ান ডলার",
    "AUD": "অস্ট্রেলিয়ান ডলার", "NZD": "নিউজিল্যান্ড ডলার",
}

PAIR_CURRENCIES = {
    "EUR/USD": {"EUR", "USD"}, "GBP/USD": {"GBP", "USD"},
    "USD/JPY": {"USD", "JPY"}, "USD/CHF": {"USD", "CHF"},
    "AUD/USD": {"AUD", "USD"}, "USD/CAD": {"USD", "CAD"},
    "NZD/USD": {"NZD", "USD"}, "EUR/GBP": {"EUR", "GBP"},
    "EUR/JPY": {"EUR", "JPY"}, "GBP/JPY": {"GBP", "JPY"},
    "EUR/CHF": {"EUR", "CHF"}, "GBP/CHF": {"GBP", "CHF"},
    "AUD/JPY": {"AUD", "JPY"}, "CAD/JPY": {"CAD", "JPY"},
    "CHF/JPY": {"CHF", "JPY"}, "NZD/JPY": {"NZD", "JPY"},
    "EUR/AUD": {"EUR", "AUD"}, "GBP/AUD": {"GBP", "AUD"},
    "AUD/CAD": {"AUD", "CAD"}, "NZD/CAD": {"NZD", "CAD"},
}


def _http_json(url: str):
    # The calendar endpoint may be cached by an intermediary. A minute-level
    # cache buster keeps the weekly calendar current without hammering the source.
    if "ff_calendar_thisweek.json" in url:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}_ts={int(time.time() // 60)}"
    req = Request(
        url,
        headers={
            "User-Agent": "mmc-signal-bot/1.0",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def _parse_time(value: str):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _translate_title(title: str) -> str:
    """Keep the source event name but provide a Bengali explanation for common events."""
    text = str(title or "").strip()
    replacements = [
        ("Non-Farm Employment Change", "নন-ফার্ম কর্মসংস্থান পরিবর্তন"),
        ("Unemployment Rate", "বেকারত্বের হার"),
        ("Consumer Price Index", "ভোক্তা মূল্য সূচক"),
        ("Core CPI", "মূল ভোক্তা মূল্য সূচক"),
        ("Producer Price Index", "উৎপাদক মূল্য সূচক"),
        ("Interest Rate Decision", "সুদের হার সিদ্ধান্ত"),
        ("GDP", "জিডিপি"),
        ("Retail Sales", "খুচরা বিক্রয়"),
        ("Manufacturing PMI", "উৎপাদন খাতের PMI"),
        ("Services PMI", "সেবা খাতের PMI"),
        ("ISM Services PMI", "ISM সেবা খাতের PMI"),
        ("Trade Balance", "বাণিজ্য ভারসাম্য"),
        ("Central Bank", "কেন্দ্রীয় ব্যাংক"),
        ("FOMC", "FOMC"),
    ]
    for source, bangla in replacements:
        if source.lower() in text.lower():
            return bangla
    return text


def fetch_calendar(force: bool = False) -> list[dict]:
    now = time.time()
    with _LOCK:
        if not force and _CACHE["events"] is not None and now - _CACHE["at"] < CACHE_TTL_SECONDS:
            return list(_CACHE["events"])
    try:
        payload = _http_json(CALENDAR_URL)
        events = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                dt = _parse_time(item.get("date") or item.get("datetime") or item.get("time"))
                if dt is None:
                    continue
                impact = str(item.get("impact") or "").strip().lower()
                events.append({
                    "id": f"{dt.isoformat()}|{item.get('country','')}|{item.get('title','')}",
                    "time_utc": dt,
                    "currency": str(item.get("country") or item.get("currency") or "").upper(),
                    "title": str(item.get("title") or "").strip(),
                    "title_bn": _translate_title(item.get("title") or ""),
                    "impact": impact,
                    "forecast": item.get("forecast"),
                    "previous": item.get("previous"),
                    "actual": item.get("actual"),
                })
        events.sort(key=lambda x: x["time_utc"])

        # Never replace known-good calendar data with an empty response. This
        # prevents a transient upstream/API failure from making all News Events
        # disappear from the dashboard.
        if events:
            with _LOCK:
                _CACHE["events"] = events
                _CACHE["at"] = now
            return list(events)

        with _LOCK:
            return list(_CACHE["events"] or [])
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        with _LOCK:
            return list(_CACHE["events"] or [])


def _relevant_currencies(pair: str, market_mode: str) -> set[str]:
    if market_mode == "crypto":
        return {"USD"}
    return PAIR_CURRENCIES.get(pair.upper(), set())


def _event_payload(event: dict, now: datetime) -> dict:
    delta = (event["time_utc"] - now).total_seconds()
    return {
        "id": event["id"],
        "currency": event["currency"],
        "currency_bn": CURRENCY_NAMES.get(event["currency"], event["currency"]),
        "title": event["title"],
        "title_bn": event["title_bn"],
        "impact": event["impact"],
        "forecast": event.get("forecast"),
        "previous": event.get("previous"),
        "actual": event.get("actual"),
        "event_time_utc": event["time_utc"].isoformat(timespec="seconds"),
        "minutes_to_event": round(delta / 60, 1),
        "five_minute_alert": 0 <= delta <= 300,
    }


def get_news_alert(pair: str, market_mode: str, alert_minutes: int = 5) -> dict:
    now = datetime.now(timezone.utc)
    currencies = _relevant_currencies(pair, market_mode)
    events = fetch_calendar()
    relevant = [e for e in events if e["currency"] in currencies and e["time_utc"] >= now - timedelta(minutes=1)]
    alert_window = [e for e in relevant if 0 <= (e["time_utc"] - now).total_seconds() <= alert_minutes * 60]
    upcoming = [e for e in relevant if 0 <= (e["time_utc"] - now).total_seconds() <= 30 * 60]
    alert_window.sort(key=lambda e: (0 if e["impact"] == "high" else 1, e["time_utc"]))
    upcoming.sort(key=lambda e: e["time_utc"])

    active = _event_payload(alert_window[0], now) if alert_window else None
    if active:
        active["signal"] = "NEWS_ALERT"
        active["signal_bn"] = "নিউজ অ্যালার্ট"
        active["recommendation_bn"] = "নিউজ প্রকাশের আগে নতুন ট্রেড নেওয়ার ঝুঁকি বেশি। নিউজের ৫ মিনিট আগে প্রস্তুত থাকুন; এটি নিশ্চিত BUY/SELL পূর্বাভাস নয়।"

    return {
        "ok": True,
        "pair": pair,
        "market_mode": market_mode,
        "checked_at_utc": now.isoformat(timespec="seconds"),
        "alert": active,
        "upcoming": [_event_payload(e, now) for e in upcoming[:5]],
        "source": "Forex Factory weekly economic calendar",
    }


def _prediction_bn(impact: str, minutes_to_event: float) -> str:
    if 0 <= minutes_to_event <= 5:
        if impact == "high":
            return "৫ মিনিটের প্রি-নিউজ সতর্কতা: ভোলাটিলিটি দ্রুত বাড়তে পারে।"
        if impact == "medium":
            return "৫ মিনিটের প্রি-নিউজ সতর্কতা: স্বাভাবিকের চেয়ে বেশি মুভ হতে পারে।"
        return "৫ মিনিটের প্রি-নিউজ সতর্কতা: নিউজের সময় মুভমেন্ট হতে পারে।"
    if impact == "high":
        return "উচ্চ প্রভাবের নির্ধারিত নিউজ—আগে থেকেই প্রস্তুত থাকুন।"
    if impact == "medium":
        return "মাঝারি প্রভাবের নিউজ—সম্ভাব্য মুভমেন্ট নজরে রাখুন।"
    return "কম প্রভাবের নিউজ—ক্যালেন্ডার হিসেবে পর্যবেক্ষণ করুন।"


def _sentiment_for_event(event: dict, market_mode: str, pairs: list[str], sentiment_data: dict) -> dict:
    """Aggregate Alpha Vantage sentiment for all pairs affected by a calendar event."""
    affected = [pair for pair in pairs if event["currency"] in _relevant_currencies(pair, market_mode)]
    if not affected:
        return {"available": False, "label_bn": "নিউজ সেন্টিমেন্ট পাওয়া যায়নি", "score": 0.0, "articles": 0, "pairs": []}
    summaries = [pair_sentiment(pair, market_mode, sentiment_data) for pair in affected]
    available = [x for x in summaries if x.get("available")]
    if not available:
        return {"available": False, "label_bn": "এই নিউজের আগে পর্যাপ্ত Alpha Vantage sentiment নেই", "score": 0.0, "articles": 0, "pairs": affected}
    score = sum(x["score"] for x in available) / len(available)
    label = "ইতিবাচক" if score >= 0.15 else "নেতিবাচক" if score <= -0.15 else "নিরপেক্ষ"
    return {"available": True, "label_bn": label, "score": round(score, 3), "articles": sum(x["articles"] for x in available), "pairs": affected}


def get_weekly_news_overview(market_mode: str, real_pairs: list[str], crypto_pairs: list[str]) -> dict:
    """Return the week's relevant calendar news grouped across every supported pair."""
    now = datetime.now(timezone.utc)
    pairs = list(crypto_pairs if market_mode == "crypto" else real_pairs)
    pair_map = {pair.upper(): pair for pair in pairs}
    grouped: dict[str, dict] = {}
    sentiment_data = fetch_news_sentiment()

    for event in fetch_calendar():
        if event["time_utc"] < now - timedelta(minutes=1):
            continue
        affected = []
        for pair in pairs:
            if event["currency"] in _relevant_currencies(pair, market_mode):
                affected.append(pair)
        if not affected:
            continue
        payload = _event_payload(event, now)
        payload["pairs"] = affected
        payload["pair_count"] = len(affected)
        payload["prediction_bn"] = _prediction_bn(payload["impact"], payload["minutes_to_event"])
        sentiment = _sentiment_for_event(event, market_mode, pairs, sentiment_data)
        payload["news_sentiment"] = sentiment
        if sentiment["available"]:
            payload["prediction_bn"] += f" | Alpha Vantage নিউজ সেন্টিমেন্ট: {sentiment['label_bn']} ({sentiment['articles']}টি প্রাসঙ্গিক আর্টিকেল)।"
        grouped[event["id"]] = payload

    events = sorted(grouped.values(), key=lambda e: e["event_time_utc"])
    alerts = [e for e in events if e["five_minute_alert"]]
    return {
        "ok": True,
        "market_mode": market_mode,
        "checked_at_utc": now.isoformat(timespec="seconds"),
        "alert_window_minutes": 5,
        "alert_events": alerts,
        "events": events,
        "total_events": len(events),
        "total_pairs": len(pair_map),
        "source": "Forex Factory weekly economic calendar + Alpha Vantage NEWS_SENTIMENT",
        "alpha_vantage": {
            "configured": bool(sentiment_data.get("configured")),
            "articles": len(sentiment_data.get("articles", [])),
            "source": sentiment_data.get("source", "Alpha Vantage"),
        },
        "note_bn": "সপ্তাহের নির্ধারিত নিউজগুলো সব সংশ্লিষ্ট পেয়ার অনুযায়ী দেখানো হয়। নিউজের ৫ মিনিট আগে প্রি-নিউজ সতর্কতা আসে। Alpha Vantage প্রকাশিত নিউজের sentiment দিয়ে অতিরিক্ত context দেয়; এটি নিশ্চিত BUY/SELL দিকের পূর্বাভাস নয়।",
    }
