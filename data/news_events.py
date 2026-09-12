"""Scheduled Forex market-news events for the dashboard."""
from __future__ import annotations
import re,threading
from datetime import datetime,timezone,timedelta
from html.parser import HTMLParser
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo
from data.news_calendar import fetch_calendar,_event_payload,_prediction_bn,_relevant_currencies
from data.alpha_vantage_news import fetch_news_sentiment,pair_sentiment
LIVE_CALENDAR_URLS=("https://www.forexfactory.com/calendar?month=this","https://calendar.forexfactory.com/calendar"); LIVE_CACHE_TTL_SECONDS=60; _LIVE_CACHE={"events":None,"at":0.0}; _LKG_NEWS={}; _DIRECTION_CACHE={}; _CACHE_LOCK=threading.Lock()
class _CalendarParser(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.rows=[];self._row=None;self._cell=None;self._span_title=""
    @staticmethod
    def _has_class(attrs,name):return name in dict(attrs).get("class","").split()
    def handle_starttag(self,tag,attrs):
        if tag=="tr" and self._has_class(attrs,"calendar_row"):self._row={k:"" for k in ("date","time","currency","impact","event","actual","forecast","previous")}
        elif tag=="td" and self._row is not None:
            classes=dict(attrs).get("class","").split();field=next((x for x in ("date","time","currency","impact","event","actual","forecast","previous") if x in classes),None);self._cell={"field":field,"text":""}
        elif tag=="span" and self._cell is not None:self._span_title=dict(attrs).get("title","")
    def handle_data(self,data):
        if self._cell is not None:self._cell["text"]+=data
    def handle_endtag(self,tag):
        if tag=="td" and self._cell is not None and self._row is not None:
            field=self._cell.get("field");text=re.sub(r"\s+"," ",self._cell.get("text","")).strip()
            if field:self._row[field]=(self._span_title or text) if field=="impact" else text
            self._cell=None;self._span_title=""
        elif tag=="tr" and self._row is not None:
            if self._row.get("currency") and self._row.get("event"):self.rows.append(self._row)
            self._row=None
def _live_html_calendar():
    now=datetime.now(timezone.utc)
    with _CACHE_LOCK:cached=list(_LIVE_CACHE["events"] or []);cached_at=_LIVE_CACHE["at"]
    if cached and now.timestamp()-cached_at<LIVE_CACHE_TTL_SECONDS:return cached
    html=""
    for url in LIVE_CALENDAR_URLS:
        try:
            req=Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; mmc-signal-bot/1.0)","Accept":"text/html,application/xhtml+xml","Cache-Control":"no-cache"})
            with urlopen(req,timeout=12) as response:html=response.read().decode("utf-8",errors="replace")
            parser=_CalendarParser();parser.feed(html)
            if parser.rows:break
        except (HTTPError,URLError,TimeoutError,OSError,ValueError):continue
    else:return cached
    parser=_CalendarParser();parser.feed(html)
    if not parser.rows:return cached
    page_tz,current_year,current_date=ZoneInfo("Europe/London"),now.year,None;events=[]
    for row in parser.rows:
        date_text,time_text=row.get("date","").strip(),row.get("time","").strip()
        if date_text:
            m=re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})",date_text,re.I)
            if m:current_date=(current_year,datetime.strptime(m.group(1)[:3].title(),"%b").month,int(m.group(2)))
        if not current_date:continue
        if not time_text or "all day" in time_text.lower() or "tentative" in time_text.lower():hour,minute=12,0
        else:
            m=re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)",time_text,re.I)
            if not m:continue
            hour,minute=int(m.group(1)),int(m.group(2));hour=hour+12 if m.group(3).lower()=="pm" and hour!=12 else 0 if m.group(3).lower()=="am" and hour==12 else hour
        try:dt=datetime(*current_date,hour,minute,tzinfo=page_tz).astimezone(timezone.utc)
        except ValueError:continue
        impact_text,currency,title=row.get("impact","").lower(),row.get("currency","").upper(),row.get("event","").strip();impact="high" if "high" in impact_text else "medium" if ("medium" in impact_text or "med" in impact_text) else "low"
        events.append({"id":f"{dt.isoformat()}|{currency}|{title}","time_utc":dt,"currency":currency,"title":title,"title_bn":title,"impact":impact,"forecast":row.get("forecast",""),"previous":row.get("previous",""),"actual":row.get("actual","")})
    events.sort(key=lambda x:x["time_utc"])
    if events:
        with _CACHE_LOCK:_LIVE_CACHE.update({"events":list(events),"at":now.timestamp()})
    return list(events or cached)
def _calendar_events_current():
    try:
        live=_live_html_calendar();now=datetime.now(timezone.utc)
        if any(e.get("time_utc") and e["time_utc"]>=now-timedelta(minutes=1) for e in live):return live,"Forex Factory live calendar"
    except (HTTPError,URLError,TimeoutError,OSError,ValueError):pass
    try:weekly=fetch_calendar()
    except Exception:weekly=[]
    return weekly,"Forex Factory weekly economic calendar (backup)"
def _payload_events(source_events,currencies,selected_pair,now):
    events=[]
    for event in source_events:
        if event["time_utc"]<now-timedelta(minutes=1) or event["currency"] not in currencies:continue
        payload=_event_payload(event,now);payload.update({"pairs":[selected_pair],"pair_count":1,"prediction_bn":_prediction_bn(payload["impact"],payload["minutes_to_event"]),"news_sentiment":{"available":False,"label_bn":"দিকের জন্য আলাদা বিশ্লেষণ প্রয়োজন","score":0.0,"articles":0,"pairs":[selected_pair]}});events.append(payload)
    events.sort(key=lambda e:e["event_time_utc"]);return events
def get_weekly_news_events_for_pair(market_mode,real_pairs,selected_pair):
    now=datetime.now(timezone.utc);mode=market_mode.lower();selected_pair=selected_pair.upper()
    if selected_pair not in {p.upper() for p in real_pairs}:return {"ok":False,"selected_pair":selected_pair,"events":[],"alert_events":[],"error":"অবৈধ মার্কেট।"}
    events=_payload_events(*(_calendar_events_current()),_relevant_currencies(selected_pair),selected_pair,now) if False else None
    source_events,source_name=_calendar_events_current();events=_payload_events(source_events,_relevant_currencies(selected_pair),selected_pair,now);key=(mode,selected_pair)
    if events:
        with _CACHE_LOCK:
            if _LKG_NEWS.get(key,{}).get("id")!=events[0].get("id"):_LKG_NEWS[key]=dict(events[0])
    else:
        with _CACHE_LOCK:saved=dict(_LKG_NEWS.get(key) or {})
        if saved:events=[saved];source_name="Last Known Good News (Forex Factory)"
    with _CACHE_LOCK:has_lkg=key in _LKG_NEWS
    return {"ok":True,"market_mode":mode,"selected_pair":selected_pair,"checked_at_utc":now.isoformat(timespec="seconds"),"alert_window_minutes":5,"alert_events":[e for e in events if e.get("five_minute_alert")],"events":events,"total_events":len(events),"total_pairs":1,"source":source_name,"alpha_vantage":{"called":False,"reason_bn":"News Events দেখানোর জন্য Alpha Vantage কল করা হয়নি।"},"last_known_good":has_lkg,"note_bn":"সপ্তাহের নির্ধারিত Forex news এখানে দেখানো হচ্ছে। সাময়িক source সমস্যা হলে Last Known Good News রাখা হবে।"}
def _direction_confidence(score,direction):
    magnitude=min(abs(float(score or 0.0)),1.0)
    if direction=="WAIT":return round(max(35.0,50.0-magnitude*25.0)),"কম"
    confidence=round(50.0+magnitude*45.0);return confidence,"উচ্চ" if confidence>=80 else "মাঝারি" if confidence>=65 else "কম"
def _direction_from_sentiment(selected_pair,event_currency,sentiment):
    score=float(sentiment.get("score") or 0.0)
    if abs(score)<0.15:
        c,l=_direction_confidence(score,"WAIT");return "WAIT","Alpha Vantage sentiment যথেষ্ট bullish/bearish নয়; pre-news bias নিশ্চিত নয়।",c,l
    parts=selected_pair.upper().split("/",1);base,quote=parts if len(parts)==2 else (parts[0],"USD");currency,positive=str(event_currency or "").upper(),score>0
    if currency==base:direction,basis=("UP" if positive else "DOWN"),f"{currency} sentiment {'ইতিবাচক' if positive else 'নেতিবাচক'}; এটি pair-এর base currency।"
    elif currency==quote:direction,basis=("DOWN" if positive else "UP"),f"{currency} sentiment {'ইতিবাচক' if positive else 'নেতিবাচক'}; এটি pair-এর quote currency।"
    else:direction,basis="WAIT","নিউজের currency নির্বাচিত pair-এর সঙ্গে সরাসরি মেলে না।"
    c,l=_direction_confidence(score,direction);return direction,basis,c,l
def get_news_direction_for_pair(market_mode,real_pairs,selected_pair):
    mode,selected_pair=market_mode.lower(),selected_pair.upper();data=get_weekly_news_events_for_pair(mode,real_pairs,selected_pair);upcoming=[e for e in data.get("events",[]) if e.get("impact") in {"high","medium","low"} and float(e.get("minutes_to_event") or 0)>=0][:8]
    if not upcoming:return {"ok":True,"needed":False,"pair":selected_pair,"events":[],"source":"Alpha Vantage NEWS_SENTIMENT"}
    try:sentiment=pair_sentiment(selected_pair,fetch_news_sentiment())
    except Exception as exc:return {"ok":True,"needed":True,"pair":selected_pair,"events":[{**e,"direction":"WAIT","confidence_pct":35,"confidence_label_bn":"কম","direction_basis_bn":"Alpha Vantage সাময়িকভাবে পাওয়া যায়নি; direction নিশ্চিত নয়।"} for e in upcoming],"source":"Alpha Vantage NEWS_SENTIMENT","alpha_vantage_error":str(exc)}
    enriched=[]
    for event in upcoming:
        key=f"{mode}|{selected_pair}|{event.get('event_time_utc')}|{event.get('currency')}|{event.get('title_bn')}"
        with _CACHE_LOCK:cached=_DIRECTION_CACHE.get(key)
        if cached:enriched.append(dict(cached));continue
        direction,basis,c,label=_direction_from_sentiment(selected_pair,event.get("currency"),sentiment);item=dict(event);item.update({"direction":direction,"confidence_pct":c,"confidence_label_bn":label,"direction_basis_bn":basis,"news_sentiment":sentiment,"selected_pair":selected_pair,"checked_at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds")})
        with _CACHE_LOCK:_DIRECTION_CACHE[key]=dict(item)
        enriched.append(item)
    nearest=enriched[0];return {"ok":True,"needed":True,"pair":selected_pair,"events":enriched,"event":nearest,"direction":nearest.get("direction","WAIT"),"confidence_pct":nearest.get("confidence_pct",35),"source":"Alpha Vantage NEWS_SENTIMENT"}
