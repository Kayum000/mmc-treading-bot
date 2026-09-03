"""Scheduled market-news events for the dashboard.

Calendar data is kept separate from Alpha Vantage. The primary calendar export is
used when it is current; if that public export is stale/empty, a live Forex Factory
calendar page is used as a fallback. Alpha Vantage is only queried by the explicit
news-direction helper when a high-impact event is within five minutes.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from data.news_calendar import (
    fetch_calendar,
    _event_payload,
    _prediction_bn,
    _relevant_currencies,
)
from data.alpha_vantage_news import fetch_news_sentiment, pair_sentiment

LIVE_CALENDAR_URL = "https://calendar.forexfactory.com/calendar"


class _CalendarParser(HTMLParser):
    """Small stdlib-only parser for Forex Factory calendar table rows."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._row = None
        self._cell = None
        self._span_title = ""

    @staticmethod
    def _has_class(attrs, name: str) -> bool:
        classes = dict(attrs).get("class", "")
        return name in classes.split()

    def handle_starttag(self, tag, attrs):
        if tag == "tr" and self._has_class(attrs, "calendar_row"):
            self._row = {"date": "", "time": "", "currency": "", "impact": "", "event": "", "actual": "", "forecast": "", "previous": ""}
        elif tag == "td" and self._row is not None:
            classes = dict(attrs).get("class", "").split()
            field = next((x for x in ("date", "time", "currency", "impact", "event", "actual", "forecast", "previous") if x in classes), None)
            self._cell = {"field": field, "text": "", "title": ""}
        elif tag == "span" and self._cell is not None:
            self._span_title = dict(attrs).get("title", "")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None and self._row is not None:
            field = self._cell.get("field")
            text = re.sub(r"\s+", " ", self._cell.get("text", "")).strip()
            if field:
                if field == "impact":
                    title = self._span_title or text
                    self._row[field] = title
                else:
                    self._row[field] = text
            self._cell = None
            self._span_title = ""
        elif tag == "tr" and self._row is not None:
            if self._row.get("currency") and self._row.get("event"):
                self.rows.append(self._row)
            self._row = None


def _live_html_calendar() -> list[dict]:
    """Fetch current calendar HTML and normalize visible calendar rows."""
    req = Request(
        LIVE_CALENDAR_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; mmc-signal-bot/1.0)",
            "Accept": "text/html,application/xhtml+xml",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urlopen(req, timeout=12) as response:
        html = response.read().decode("utf-8", errors="replace")

    parser = _CalendarParser()
    parser.feed(html)
    if not parser.rows:
        return []

    # Forex Factory's public calendar currently displays in Europe/London by default.
    # Convert the displayed local date/time to UTC before exposing it to the app.
    page_tz = ZoneInfo("Europe/London")
    current_year = datetime.now(timezone.utc).year
    current_date = None
    events = []
    for row in parser.rows:
        date_text = row.get("date", "").strip()
        time_text = row.get("time", "").strip()
        if date_text:
            m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})", date_text, re.I)
            if m:
                month = datetime.strptime(m.group(1)[:3].title(), "%b").month
                current_date = (current_year, month, int(m.group(2)))
        if not current_date:
            continue

        if not time_text or "all day" in time_text.lower() or "day " in time_text.lower() or "tentative" in time_text.lower():
            hour, minute = 12, 0
        else:
            tm = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)", time_text, re.I)
            if not tm:
                continue
            hour, minute = int(tm.group(1)), int(tm.group(2))
            if tm.group(3).lower() == "pm" and hour != 12:
                hour += 12
            if tm.group(3).lower() == "am" and hour == 12:
                hour = 0

        try:
            local_dt = datetime(*current_date, hour, minute, tzinfo=page_tz)
            dt = local_dt.astimezone(timezone.utc)
        except ValueError:
            continue

        impact_text = row.get("impact", "").lower()
        if "high" in impact_text:
            impact = "high"
        elif "medium" in impact_text or "med" in impact_text:
            impact = "medium"
        elif "low" in impact_text:
            impact = "low"
        else:
            impact = "low"

        currency = row.get("currency", "").upper()
        title = row.get("event", "").strip()
        events.append({
            "id": f"{dt.isoformat()}|{currency}|{title}",
            "time_utc": dt,
            "currency": currency,
            "title": title,
            "title_bn": title,
            "impact": impact,
            "forecast": row.get("forecast", ""),
            "previous": row.get("previous", ""),
            "actual": row.get("actual", ""),
        })

    events.sort(key=lambda x: x["time_utc"])
    return events


def _calendar_events_current() -> tuple[list[dict], str]:
    """Prefer the JSON export, but reject a stale export with no current events."""
    now = datetime.now(timezone.utc)
    try:
        events = fetch_calendar(force=True)
    except Exception:
        events = []
    future = [e for e in events if e.get("time_utc") and e["time_utc"] >= now - timedelta(minutes=1)]
    # The public JSON feed can remain stuck on an old week. If it has no current
    # event, use the live calendar page rather than showing an empty News Events box.
    if future:
        return events, "Forex Factory weekly economic calendar"
    try:
        live = _live_html_calendar()
        if live:
            return live, "Forex Factory live calendar"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        pass
    return events, "Forex Factory weekly economic calendar"


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
    source_events, source_name = _calendar_events_current()
    events = []
    for event in source_events:
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
        "source": source_name,
        "alpha_vantage": {
            "called": False,
            "reason_bn": "News Events দেখানোর জন্য Alpha Vantage কল করা হয়নি।",
        },
        "note_bn": (
            "সপ্তাহের নির্ধারিত Forex/market news এখানে দেখানো হচ্ছে। "
            "News Direction দরকার হলে Market Status থেকে আলাদা করে Alpha Vantage sentiment নেওয়া হবে।"
        ),
    }


def get_news_direction_for_pair(
    market_mode: str,
    real_pairs: list[str],
    crypto_pairs: list[str],
    selected_pair: str,
) -> dict:
    """Calculate direction only when a high-impact event is within five minutes."""
    selected_pair = selected_pair.upper()
    now = datetime.now(timezone.utc)
    data = get_weekly_news_events_for_pair(market_mode, real_pairs, crypto_pairs, selected_pair)
    direction_event = next(
        (e for e in data.get("events", []) if e.get("impact") == "high" and 0 <= float(e.get("minutes_to_event") or 0) <= 5.0),
        None,
    )
    if direction_event is None:
        return {"ok": True, "needed": False, "pair": selected_pair, "events": []}

    sentiment_data = fetch_news_sentiment()
    sentiment = pair_sentiment(selected_pair, market_mode, sentiment_data)
    score = float(sentiment.get("score") or 0.0)
    if abs(score) < 0.15:
        direction = "WAIT"
        basis = "পর্যাপ্ত bullish/bearish sentiment নেই; নিউজের actual result না আসা পর্যন্ত দিক নিশ্চিত নয়।"
    else:
        positive = score > 0
        base, quote = (selected_pair.split("/", 1) if market_mode != "crypto" else (selected_pair.split("/", 1)[0], "USD"))
        currency = str(direction_event.get("currency", "")).upper()
        if currency == base:
            direction = "UP" if positive else "DOWN"
            basis = f"{currency} sentiment {'ইতিবাচক' if positive else 'নেতিবাচক'}; এটি pair-এর base currency।"
        elif currency == quote:
            direction = "DOWN" if positive else "UP"
            basis = f"{currency} sentiment {'ইতিবাচক' if positive else 'নেতিবাচক'}; এটি pair-এর quote currency।"
        else:
            direction = "WAIT"
            basis = "এই নিউজের sentiment নির্বাচিত pair-এর মুদ্রার সঙ্গে সরাসরি মেলে না।"

    event = dict(direction_event)
    event["direction"] = direction
    event["direction_basis_bn"] = basis
    event["news_sentiment"] = sentiment
    event["selected_pair"] = selected_pair
    event["checked_at_utc"] = now.isoformat(timespec="seconds")
    return {
        "ok": True,
        "needed": True,
        "pair": selected_pair,
        "event": event,
        "source": "Alpha Vantage NEWS_SENTIMENT",
    }
