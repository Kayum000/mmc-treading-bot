"""All-pair scheduled Forex news for the News Events dashboard."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from data.news_events import _calendar_events_current
from data.news_calendar import _event_payload, _prediction_bn


def _pair_matches_currency(pair: str, currency: str) -> bool:
    parts = str(pair or "").upper().split("/", 1)
    return len(parts) == 2 and currency.upper() in parts


def get_all_news_events(market_mode: str, real_pairs: list[str], crypto_pairs: list[str]) -> dict:
    """Return upcoming calendar events once, with every affected pair listed."""
    now = datetime.now(timezone.utc)
    mode = str(market_mode or "real").strip().lower()
    pairs = list(crypto_pairs if mode == "crypto" else real_pairs)
    source_events, source_name = _calendar_events_current()
    events = []

    for source in source_events:
        event_time = source.get("time_utc")
        currency = str(source.get("currency") or "").upper()
        if not event_time or event_time < now - timedelta(minutes=1) or not currency:
            continue
        affected_pairs = [pair for pair in pairs if _pair_matches_currency(pair, currency)]
        if not affected_pairs:
            continue

        payload = _event_payload(source, now)
        payload["pairs"] = affected_pairs
        payload["pair_count"] = len(affected_pairs)
        payload["prediction_bn"] = _prediction_bn(payload.get("impact"), payload.get("minutes_to_event"))
        payload["news_sentiment"] = {
            "available": False,
            "label_bn": "দিকের জন্য আলাদা বিশ্লেষণ প্রয়োজন",
            "score": 0.0,
            "articles": 0,
            "pairs": affected_pairs,
        }
        events.append(payload)

    events.sort(key=lambda event: event.get("event_time_utc") or "")
    for number, event in enumerate(events, start=1):
        original_title = event.get("title_bn") or event.get("title") or "Economic News"
        event["news_number"] = number
        event["title_bn"] = f"{number}. {original_title}"

    return {
        "ok": True,
        "market_mode": mode,
        "checked_at_utc": now.isoformat(timespec="seconds"),
        "alert_window_minutes": 5,
        "alert_events": [event for event in events if event.get("five_minute_alert")],
        "events": events,
        "total_events": len(events),
        "total_pairs": len(pairs),
        "source": source_name,
        "alpha_vantage": {"called": False, "reason_bn": "News Events দেখানোর জন্য Alpha Vantage কল করা হয়নি।"},
        "note_bn": "সব configured pair-এর upcoming Forex/market news একসাথে দেখানো হচ্ছে এবং সময় অনুযায়ী সাজানো হয়েছে। প্রতিটি নিউজ সময় অনুযায়ী ১, ২, ৩… নম্বরে সাজানো। Pre-News Direction নির্বাচিত মার্কেটের জন্য আলাদা cached analysis হিসেবে থাকবে।",
    }
