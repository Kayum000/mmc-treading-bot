"""Pair-specific news direction and next 1-minute candle guidance."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from data.news_events import (
    get_weekly_news_events_for_pair,
    get_news_direction_for_pair as get_cached_news_direction_for_pair,
)


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
    """Compatibility overview using the single event-keyed direction cache.

    This function deliberately does not import or call Alpha Vantage directly.
    Any imminent high-impact direction is obtained through the same cached
    endpoint implementation used by Flask, preventing duplicate requests for
    the same mode/pair/news event.
    """
    market_mode = market_mode.lower()
    selected_pair = selected_pair.upper()
    data = get_weekly_news_events_for_pair(market_mode, real_pairs, crypto_pairs, selected_pair)
    enriched = []

    imminent_high = next(
        (
            event for event in data.get("events", [])
            if event.get("impact") == "high"
            and 0 <= float(event.get("minutes_to_event") or 0) <= 5.0
        ),
        None,
    )
    direction_data = None
    if imminent_high is not None:
        direction_data = get_cached_news_direction_for_pair(
            market_mode,
            real_pairs,
            crypto_pairs,
            selected_pair,
        )

    direction_event = (direction_data or {}).get("event") if direction_data else None
    direction_time = str((direction_event or {}).get("event_time_utc") or "")

    for event in data.get("events", []):
        event = dict(event)
        event_time = str(event.get("event_time_utc") or "")
        if direction_event is not None and event_time == direction_time:
            sentiment = direction_event.get("news_sentiment") or event.get("news_sentiment") or {}
            direction = str(direction_event.get("direction") or "WAIT").upper()
            basis = direction_event.get("direction_basis_bn") or "Alpha Vantage sentiment ভিত্তিক সম্ভাব্য bias।"
            event["news_sentiment"] = sentiment
        else:
            direction = "WAIT"
            basis = "Direction বিশ্লেষণ শুধু high-impact নিউজের ৫ মিনিটের window-তে করা হবে।"

        entry_utc, entry_window = _entry_window(event["event_time_utc"])
        if float(event.get("minutes_to_event") or 0) >= 0:
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
        "শুধু high-impact release-এর ৫ মিনিটের মধ্যে direction দরকার হলে event-keyed cached sentiment ব্যবহার হবে।"
    )
    return data


def get_news_direction_for_pair(market_mode: str, real_pairs: list[str], crypto_pairs: list[str], selected_pair: str) -> dict:
    """Public Flask endpoint; delegate to the event-keyed cached implementation."""
    return get_cached_news_direction_for_pair(
        market_mode,
        real_pairs,
        crypto_pairs,
        selected_pair,
    )
