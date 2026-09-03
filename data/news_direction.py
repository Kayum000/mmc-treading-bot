"""Pair-specific news direction and next 1-minute candle guidance."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from data.news_events import get_weekly_news_events_for_pair
from data.alpha_vantage_news import fetch_news_sentiment, pair_sentiment


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
    minute_start = event_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
    minute_end = minute_start + timedelta(minutes=1)
    return (
        minute_start.isoformat(timespec="seconds"),
        f"{minute_start.strftime('%H:%M')}–{minute_end.strftime('%H:%M')} UTC",
    )


def get_weekly_news_overview_for_pair(market_mode: str, real_pairs: list[str], crypto_pairs: list[str], selected_pair: str) -> dict:
    """Return calendar events for one pair and use Alpha Vantage only for direction."""
    selected_pair = selected_pair.upper()
    data = get_weekly_news_events_for_pair(market_mode, real_pairs, crypto_pairs, selected_pair)
    enriched = []

    for event in data.get("events", []):
        minutes = float(event.get("minutes_to_event") or 0)
        # Calendar display itself never calls Alpha Vantage. Only an imminent
        # high-impact release needs sentiment/direction.
        if event.get("impact") == "high" and 0 <= minutes <= 5.0:
            sentiment_data = fetch_news_sentiment()
            sentiment = pair_sentiment(selected_pair, market_mode, sentiment_data)
            direction, basis = _direction(selected_pair, market_mode, event.get("currency", ""), sentiment)
            event = dict(event)
            event["news_sentiment"] = sentiment
        else:
            direction = "WAIT"
            basis = "Direction বিশ্লেষণ শুধু high-impact নিউজের ৫ মিনিটের window-তে করা হবে।"
            event = dict(event)

        entry_utc, entry_window = _entry_window(event["event_time_utc"])
        if minutes >= 0:
            phase = "PRE-NEWS"
            action = "WAIT — নিউজের আগে entry নয়"
        else:
            phase = "POST-NEWS"
            action = f"{direction} — পরবর্তী 1M candle"
        if direction == "WAIT":
            action = "WAIT — direction নিশ্চিত নয়"

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
        "NEWS প্যানেল নির্বাচিত pair অনুযায়ী দেখাবে। Calendar event দেখাতে Alpha Vantage কল করা হয় না; "
        "শুধু high-impact release-এর ৫ মিনিটের মধ্যে direction দরকার হলে Alpha Vantage sentiment ব্যবহার হবে।"
    )
    return data
