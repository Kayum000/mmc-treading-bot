"""Pair-specific news direction and next 1-minute candle guidance."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from data.news_calendar import get_weekly_news_overview


def _pair_currencies(pair: str, market_mode: str) -> tuple[str, str]:
    if market_mode == "crypto":
        base = pair.upper().split("/")[0]
        return base, "USD"
    base, quote = pair.upper().split("/", 1)
    return base, quote


def _direction(pair: str, market_mode: str, event_currency: str, sentiment: dict) -> tuple[str, str]:
    """Return a cautious news-based bias, never a guaranteed trade direction."""
    score = float(sentiment.get("score") or 0.0)
    if abs(score) < 0.15:
        return "WAIT", "পর্যাপ্ত bullish/bearish sentiment নেই; নিউজের actual result না আসা পর্যন্ত দিক নিশ্চিত নয়।"

    base, quote = _pair_currencies(pair, market_mode)
    currency = event_currency.upper()
    positive = score > 0
    if currency == base:
        direction = "UP" if positive else "DOWN"
        basis = f"{currency} sentiment {'ইতিবাচক' if positive else 'নেতিবাচক'}; এটি pair-এর base currency।"
    elif currency == quote:
        direction = "DOWN" if positive else "UP"
        basis = f"{currency} sentiment {'ইতিবাচক' if positive else 'নেতিবাচক'}; এটি pair-এর quote currency।"
    else:
        return "WAIT", "এই নিউজের sentiment নির্বাচিত pair-এর মুদ্রার সঙ্গে সরাসরি মেলে না।"
    return direction, basis


def _entry_window(event_time_iso: str) -> tuple[str, str]:
    event_time = datetime.fromisoformat(event_time_iso.replace("Z", "+00:00"))
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    event_time = event_time.astimezone(timezone.utc)
    # Use the first complete 1-minute candle after the scheduled release.
    minute_start = event_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
    minute_end = minute_start + timedelta(minutes=1)
    return (
        minute_start.isoformat(timespec="seconds"),
        f"{minute_start.strftime('%H:%M')}–{minute_end.strftime('%H:%M')} UTC",
    )


def get_weekly_news_overview_for_pair(market_mode: str, real_pairs: list[str], crypto_pairs: list[str], selected_pair: str) -> dict:
    data = get_weekly_news_overview(market_mode, real_pairs, crypto_pairs)
    selected_pair = selected_pair.upper()
    enriched = []
    for event in data.get("events", []):
        if selected_pair not in event.get("pairs", []):
            continue
        sentiment = event.get("news_sentiment") or {}
        direction, basis = _direction(selected_pair, market_mode, event.get("currency", ""), sentiment)
        entry_utc, entry_window = _entry_window(event["event_time_utc"])
        minutes = float(event.get("minutes_to_event") or 0)
        if minutes >= 0:
            phase = "PRE-NEWS"
            action = "WAIT — নিউজের আগে entry নয়"
        else:
            phase = "POST-NEWS"
            action = f"{direction} — পরবর্তী 1M candle"
        if direction == "WAIT":
            action = "WAIT — direction নিশ্চিত নয়"
        event = dict(event)
        event["selected_pair"] = selected_pair
        event["direction"] = direction
        event["direction_basis_bn"] = basis
        event["entry_candle_utc"] = entry_utc
        event["entry_candle_bn"] = entry_window
        event["trade_phase_bn"] = phase
        event["trade_action_bn"] = action
        event["prediction_bn"] = (
            f"🎯 {selected_pair} | {phase} | NEWS: {event['event_time_utc']} | "
            f"ENTRY CANDLE: {entry_window} | DIRECTION: {direction} | {basis} | {action}।"
        )
        enriched.append(event)

    data = dict(data)
    data["selected_pair"] = selected_pair
    data["events"] = enriched
    data["alert_events"] = [e for e in enriched if e.get("five_minute_alert")]
    data["note_bn"] = (
        "NEWS প্যানেল এখন নির্বাচিত pair অনুযায়ী দেখাবে: NEWS TIME, পরবর্তী 1M ENTRY CANDLE এবং সম্ভাব্য UP/DOWN bias। "
        "PRE-NEWS অবস্থায় WAIT থাকবে; Alpha Vantage sentiment থাকলে সেটি শুধু সম্ভাব্য bias হিসেবে ব্যবহৃত হবে, নিশ্চিত prediction নয়।"
    )
    return data
