"""Pair-specific Forex news direction and next 1-minute candle guidance."""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from data.news_events import get_weekly_news_events_for_pair,get_news_direction_for_pair as get_cached_news_direction_for_pair

def _pair_currencies(pair):
    return tuple(pair.upper().split("/",1))
def _entry_window(event_time_iso):
    event_time=datetime.fromisoformat(event_time_iso.replace("Z","+00:00"));event_time=event_time.replace(tzinfo=timezone.utc) if event_time.tzinfo is None else event_time.astimezone(timezone.utc);minute_start=event_time.replace(second=0,microsecond=0)+timedelta(minutes=1);minute_end=minute_start+timedelta(minutes=1);return minute_start.isoformat(timespec="seconds"),f"{minute_start.strftime('%H:%M')}–{minute_end.strftime('%H:%M')} UTC"
def get_weekly_news_overview_for_pair(market_mode,real_pairs,selected_pair):
    mode=market_mode.lower();selected_pair=selected_pair.upper();data=get_weekly_news_events_for_pair(mode,real_pairs,selected_pair);enriched=[];imminent=next((e for e in data.get("events",[]) if e.get("impact")=="high" and 0<=float(e.get("minutes_to_event") or 0)<=5.0),None);direction_data=get_cached_news_direction_for_pair(mode,real_pairs,selected_pair) if imminent else None;direction_event=(direction_data or {}).get("event") if direction_data else None;direction_time=str((direction_event or {}).get("event_time_utc") or "")
    for source_event in data.get("events",[]):
        event=dict(source_event);event_time=str(event.get("event_time_utc") or "");direction=str((direction_event or {}).get("direction") or "WAIT").upper() if direction_event and event_time==direction_time else "WAIT";basis=(direction_event or {}).get("direction_basis_bn") or "Direction বিশ্লেষণ শুধু high-impact নিউজের ৫ মিনিটের window-তে করা হবে.";entry_utc,entry_window=_entry_window(event["event_time_utc"]);phase="PRE-NEWS" if float(event.get("minutes_to_event") or 0)>=0 else "POST-NEWS";action="WAIT — নিউজের আগে entry নয়" if phase=="PRE-NEWS" else f"{direction} — পরবর্তী 1M candle";action="WAIT — direction নিশ্চিত নয়" if direction=="WAIT" else action;event.update({"selected_pair":selected_pair,"direction":direction,"direction_basis_bn":basis,"entry_candle_utc":entry_utc,"entry_candle_bn":entry_window,"trade_phase_bn":phase,"trade_action_bn":action,"prediction_bn":f"🎯 {selected_pair} | {phase} | NEWS: {event['event_time_utc']} | ENTRY CANDLE: {entry_window} | DIRECTION: {direction} | {basis} | {action}।"});enriched.append(event)
    data=dict(data);data["selected_pair"]=selected_pair;data["events"]=enriched;data["alert_events"]=[e for e in enriched if e.get("five_minute_alert")];return data
def get_news_direction_for_pair(market_mode,real_pairs,selected_pair):return get_cached_news_direction_for_pair(market_mode,real_pairs,selected_pair)
