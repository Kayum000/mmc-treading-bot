"""Scheduled market-news events for the dashboard.

Calendar data is kept separate from Alpha Vantage. The live Forex Factory
calendar is preferred because the public weekly export can lag; the weekly
export remains a backup. Alpha Vantage is used for pre-news sentiment and
the resulting direction is cached per mode/pair/event.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from data.news_calendar import fetch_calendar, _event_payload, _prediction_bn, _relevant_currencies
from data.alpha_vantage_news import fetch_news_sentiment, pair_sentiment

LIVE_CALENDAR_URLS = (
    "https://www.forexfactory.com/calendar?month=this",
    "https://calendar.forexfactory.com/calendar",
)
LIVE_CACHE_TTL_SECONDS = 60
_LIVE_CACHE = {"events": None, "at": 0.0}
_LKG_NEWS = {}
_DIRECTION_CACHE = {}
_CACHE_LOCK = threading.Lock()


class _CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._row = None
        self._cell = None
        self._span_title = ""

    @staticmethod
    def _has_class(attrs, name: str) -> bool:
        return name in dict(attrs).get("class", "").split()

    def handle_starttag(self, tag, attrs):
        if tag == "tr" and self._has_class(attrs, "calendar_row"):
            self._row = {"date": "", "time": "", "currency": "", "impact": "", "event": "", "actual": "", "forecast": "", "previous": ""}
        elif tag == "td" and self._row is not None:
            classes = dict(attrs).get("class", "").split()
            field = next((x for x in ("date", "time", "currency", "impact", "event", "actual", "forecast", "previous") if x in classes), None)
            self._cell = {"field": field, "text": ""}
        elif tag == "span" and self._cell is not None:
            title = dict(attrs).get("title", "")
            if title:
                self._span_title = title

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None and self._row is not None:
            field = self._cell.get("field")
            text = re.sub(r"\s+", " ", self._cell.get("text", "")).strip()
            if field:
                self._row[field] = (self._span_title or text) if field == "impact" else text
            self._cell = None
            self._span_title = ""
        elif tag == "tr" and self._row is not None:
            if self._row.get("currency") and self._row.get("event"):
                self.rows.append(self._row)
            self._row = None


def _live_html_calendar() -> list[dict]:
    now = datetime.now(timezone.utc)
    with _CACHE_LOCK:
        cached = list(_LIVE_CACHE["events"] or [])
        cached_at = _LIVE_CACHE["at"]
    if cached and now.timestamp() - cached_at < LIVE_CACHE_TTL_SECONDS:
        return cached

    html = ""
    for url in LIVE_CALENDAR_URLS:
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; mmc-signal-bot/1.0)", "Accept": "text/html,application/xhtml+xml", "Cache-Control": "no-cache"})
            with urlopen(req, timeout=12) as response:
                html = response.read().decode("utf-8", errors="replace")
            parser = _CalendarParser()
            parser.feed(html)
            if parser.rows:
                break
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            continue
    else:
        return cached

    parser = _CalendarParser()
    parser.feed(html)
    if not parser.rows:
        return cached

    page_tz = ZoneInfo("Europe/London")
    current_year = now.year
    current_date = None
    events = []
    for row in parser.rows:
        date_text = row.get("date", "").strip()
        time_text = row.get("time", "").strip()
        if date_text:
            m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})", date_text, re.I)
            if m:
                current_date = (current_year, datetime.strptime(m.group(1)[:3].title(), "%b").month, int(m.group(2)))
        if not current_date:
            continue
        if not time_text or "all day" in time_text.lower() or "tentative" in time_text.lower():
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
            dt = datetime(*current_date, hour, minute, tzinfo=page_tz).astimezone(timezone.utc)
        except ValueError:
            continue
        impact_text = row.get("impact", "").lower()
        impact = "high" if "high" in impact_text else "medium" if ("medium" in impact_text or "med" in impact_text) else "low"
        currency = row.get("currency", "").upper()
        title = row.get("event", "").strip()
        events.append({"id": f"{dt.isoformat()}|{currency}|{title}", "time_utc": dt, "currency": currency, "title": title, "title_bn": title, "impact": impact, "forecast": row.get("forecast", ""), "previous": row.get("previous", ""), "actual": row.get("actual", "")})
    events.sort(key=lambda x: x["time_utc"])
    if events:
        with _CACHE_LOCK:
            _LIVE_CACHE["events"] = list(events)
            _LIVE_CACHE["at"] = now.timestamp()
    return list(events or cached)


def _calendar_events_current() -> tuple[list[dict], str]:
    """Prefer live calendar; use weekly export only as a backup."""
    try:
        live = _live_html_calendar()
        now = datetime.now(timezone.utc)
        if any(e.get("time_utc") and e["time_utc"] >= now - timedelta(minutes=1) for e in live):
            return live, "Forex Factory live calendar"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        pass
    try:
        weekly = fetch_calendar()
    except Exception:
        weekly = []
    return weekly, "Forex Factory weekly economic calendar (backup)"


def _payload_events(source_events: list[dict], currencies: set[str], selected_pair: str, now: datetime) -> list[dict]:
    events = []
    for event in source_events:
        if event["time_utc"] < now - timedelta(minutes=1) or event["currency"] not in currencies:
            continue
        payload = _event_payload(event, now)
        payload["pairs"] = [selected_pair]
        payload["pair_count"] = 1
        payload["prediction_bn"] = _prediction_bn(payload["impact"], payload["minutes_to_event"])
        payload["news_sentiment"] = {"available": False, "label_bn": "দিকের জন্য আলাদা বিশ্লেষণ প্রয়োজন", "score": 0.0, "articles": 0, "pairs": [selected_pair]}
        events.append(payload)
    events.sort(key=lambda e: e["event_time_utc"])
    return events


def _lkg_key(market_mode: str, selected_pair: str) -> tuple[str, str]:
    return market_mode.lower(), selected_pair.upper()


def get_weekly_news_events_for_pair(market_mode: str, real_pairs: list[str], crypto_pairs: list[str], selected_pair: str) -> dict:
    now = datetime.now(timezone.utc)
    market_mode = market_mode.lower()
    selected_pair = selected_pair.upper()
    pairs = list(crypto_pairs if market_mode == "crypto" else real_pairs)
    if selected_pair not in {p.upper() for p in pairs}:
        return {"ok": False, "selected_pair": selected_pair, "events": [], "alert_events": [], "error": "অবৈধ মার্কেট।"}
    currencies = _relevant_currencies(selected_pair, market_mode)
    source_events, source_name = _calendar_events_current()
    events = _payload_events(source_events, currencies, selected_pair, now)
    key = _lkg_key(market_mode, selected_pair)
    if events:
        nearest = events[0]
        with _CACHE_LOCK:
            previous = _LKG_NEWS.get(key)
            if previous is None or nearest.get("id") != previous.get("id"):
                _LKG_NEWS[key] = dict(nearest)
    else:
        with _CACHE_LOCK:
            saved = dict(_LKG_NEWS.get(key) or {})
        if saved:
            events = [saved]
            source_name = "Last Known Good News (Forex Factory)"
    with _CACHE_LOCK:
        has_lkg = key in _LKG_NEWS
    return {"ok": True, "market_mode": market_mode, "selected_pair": selected_pair, "checked_at_utc": now.isoformat(timespec="seconds"), "alert_window_minutes": 5, "alert_events": [e for e in events if e.get("five_minute_alert")], "events": events, "total_events": len(events), "total_pairs": 1, "source": source_name, "alpha_vantage": {"called": False, "reason_bn": "News Events দেখানোর জন্য Alpha Vantage কল করা হয়নি।"}, "last_known_good": has_lkg, "note_bn": "সপ্তাহের নির্ধারিত Forex/market news এখানে দেখানো হচ্ছে। সাময়িক source সমস্যা হলে Last Known Good News রাখা হবে। Pre-News Direction দরকার হলে Alpha Vantage sentiment আলাদা cached request হিসেবে ব্যবহার হবে।"}


def _direction_confidence(score: float, direction: str) -> tuple[int, str]:
    """Convert Alpha Vantage sentiment strength into a conservative confidence %."""
    magnitude = min(abs(float(score or 0.0)), 1.0)
    if direction == "WAIT":
        confidence = round(max(35.0, 50.0 - magnitude * 25.0))
        return confidence, "কম"
    confidence = round(50.0 + magnitude * 45.0)
    if confidence >= 80:
        label = "উচ্চ"
    elif confidence >= 65:
        label = "মাঝারি"
    else:
        label = "কম"
    return confidence, label


def _direction_from_sentiment(selected_pair: str, event_currency: str, sentiment: dict) -> tuple[str, str, int, str]:
    score = float(sentiment.get("score") or 0.0)
    if abs(score) < 0.15:
        direction = "WAIT"
        basis = "Alpha Vantage sentiment যথেষ্ট bullish/bearish নয়; pre-news bias নিশ্চিত নয়।"
        confidence, label = _direction_confidence(score, direction)
        return direction, basis, confidence, label
    parts = selected_pair.upper().split("/", 1)
    base, quote = parts if len(parts) == 2 else (parts[0], "USD")
    currency = str(event_currency or "").upper()
    positive = score > 0
    if currency == base:
        direction = "UP" if positive else "DOWN"
        basis = f"{currency} sentiment {'ইতিবাচক' if positive else 'নেতিবাচক'}; এটি pair-এর base currency।"
    elif currency == quote:
        direction = "DOWN" if positive else "UP"
        basis = f"{currency} sentiment {'ইতিবাচক' if positive else 'নেতিবাচক'}; এটি pair-এর quote currency।"
    else:
        direction = "WAIT"
        basis = "নিউজের currency নির্বাচিত pair-এর সঙ্গে সরাসরি মেলে না।"
    confidence, label = _direction_confidence(score, direction)
    return direction, basis, confidence, label


def get_news_direction_for_pair(market_mode: str, real_pairs: list[str], crypto_pairs: list[str], selected_pair: str) -> dict:
    """Return pre-news direction for upcoming High/Medium/Low impact events.

    The event schedule/impact/time comes from the economic calendar. The
    directional bias and confidence are derived from one cached Alpha Vantage
    NEWS_SENTIMENT response, avoiding a request per event.
    """
    market_mode = market_mode.lower()
    selected_pair = selected_pair.upper()
    now = datetime.now(timezone.utc)
    data = get_weekly_news_events_for_pair(market_mode, real_pairs, crypto_pairs, selected_pair)
    upcoming = [e for e in data.get("events", []) if e.get("impact") in {"high", "medium", "low"} and float(e.get("minutes_to_event") or 0) >= 0][:8]
    if not upcoming:
        return {"ok": True, "needed": False, "pair": selected_pair, "events": [], "source": "Alpha Vantage NEWS_SENTIMENT"}
    try:
        sentiment = pair_sentiment(selected_pair, market_mode, fetch_news_sentiment())
    except Exception as exc:
        fallback = []
        for event in upcoming:
            fallback.append({**event, "direction": "WAIT", "confidence_pct": 35, "confidence_label_bn": "কম", "direction_basis_bn": "Alpha Vantage সাময়িকভাবে পাওয়া যায়নি; direction নিশ্চিত নয়।"})
        return {"ok": True, "needed": True, "pair": selected_pair, "events": fallback, "source": "Alpha Vantage NEWS_SENTIMENT", "alpha_vantage_error": str(exc)}
    enriched = []
    for event in upcoming:
        event_key = f"{market_mode}|{selected_pair}|{event.get('event_time_utc')}|{event.get('currency')}|{event.get('title_bn')}"
        with _CACHE_LOCK:
            cached = _DIRECTION_CACHE.get(event_key)
        if cached:
            enriched.append(dict(cached))
            continue
        direction, basis, confidence, confidence_label = _direction_from_sentiment(selected_pair, event.get("currency"), sentiment)
        enriched_event = dict(event)
        enriched_event.update({
            "direction": direction,
            "confidence_pct": confidence,
            "confidence_label_bn": confidence_label,
            "direction_basis_bn": basis,
            "news_sentiment": sentiment,
            "selected_pair": selected_pair,
            "checked_at_utc": now.isoformat(timespec="seconds"),
            "direction_phase": "PRE-NEWS",
            "direction_label_bn": f"⬆ UP — উপরে ({confidence}%)" if direction == "UP" else f"⬇ DOWN — নিচে ({confidence}%)" if direction == "DOWN" else f"⏸ WAIT — নিশ্চিত নয় ({confidence}%)",
        })
        with _CACHE_LOCK:
            _DIRECTION_CACHE[event_key] = dict(enriched_event)
        enriched.append(enriched_event)
    return {"ok": True, "needed": True, "pair": selected_pair, "events": enriched, "event": enriched[0], "source": "Alpha Vantage NEWS_SENTIMENT", "alpha_vantage_cached": True, "note_bn": "Direction ও confidence Alpha Vantage news sentiment-এর strength থেকে হিসাব করা PRE-NEWS সম্ভাব্য bias; actual news result/price reaction বদলে দিতে পারে। নিউজের সময়/impact economic calendar থেকে আসে।"}
