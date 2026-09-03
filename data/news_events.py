"""Forex/crypto scheduled news events without any Alpha Vantage request.

This module is intentionally calendar-only. It reuses the existing calendar cache
and formatting helpers, while keeping Alpha Vantage available only to the
explicit news-direction endpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from data.news_calendar import (
    fetch_calendar,
    _event_payload,
    _prediction_bn,
    _relevant_currencies,
)


def get_weekly_news_events_for_pair(
    market_mode: str,
    real_pairs: list[str],
    crypto_pairs: list[str],
    selected_pair: str,
) -> dict:
    """Return scheduled events for one selected pair; never calls Alpha Vantage."""
    now = datetime.now(timezone.utc)
    selected_pair = selected_pair.upper()
    pairs = list(crypto_pairs if market_mode == "crypto" else real_pairs)
    if selected_pair not in {p.upper() for p in pairs}:
        return {
            "ok": False,
            "selected_pair": selected_pair,
            "events": [],
            "alert_events": [],
            "error": "অবৈধ মার্কেট।",
        }

    currencies = _relevant_currencies(selected_pair, market_mode)
    events = []
    for event in fetch_calendar():
        if event["time_utc"] < now - timedelta(minutes=1):
            continue
        if event["currency"] not in currencies:
            continue
        payload = _event_payload(event, now)
        payload["pairs"] = [selected_pair]
        payload["pair_count"] = 1
        payload["prediction_bn"] = _prediction_bn(
            payload["impact"], payload["minutes_to_event"]
        )
        # Direction is deliberately not calculated here. It belongs to the
        # explicit /news-direction request so the News Events panel stays free
        # of Alpha Vantage calls.
        payload["news_sentiment"] = {
            "available": False,
            "label_bn": "দিকের জন্য আলাদা বিশ্লেষণ প্রয়োজন",
            "score": 0.0,
            "articles": 0,
            "pairs": [selected_pair],
        }
        events.append(payload)

    events.sort(key=lambda e: e["event_time_utc"])
    alerts = [e for e in events if e.get("five_minute_alert")]
    return {
        "ok": True,
        "market_mode": market_mode,
        "selected_pair": selected_pair,
        "checked_at_utc": now.isoformat(timespec="seconds"),
        "alert_window_minutes": 5,
        "alert_events": alerts,
        "events": events,
        "total_events": len(events),
        "total_pairs": 1,
        "source": "Forex Factory weekly economic calendar",
        "alpha_vantage": {
            "called": False,
            "reason_bn": "News Events দেখানোর জন্য Alpha Vantage কল করা হয়নি।",
        },
        "note_bn": (
            "সপ্তাহের নির্ধারিত Forex/market news এখানে দেখানো হচ্ছে। "
            "News Direction দরকার হলে Market Status থেকে আলাদা করে Alpha Vantage sentiment নেওয়া হবে।"
        ),
    }
