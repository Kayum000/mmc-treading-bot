"""Running 1-minute entry engine.

Analyzes the currently forming 1m candle and permits a new entry only during
seconds 20-25 of that candle. The signal enters the current candle; settlement
continues to use the completed current 1m candle at the minute boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import threading

import pandas as pd

from data.biquote_forex import fetch_forex_candles, fetch_latest_tick
from data.crypto_running import fetch_crypto_running_candle
from strategy.mmc import Signal, generate_signal, level_for_side
from strategy.reentry_guard import check_reentry_guard
from performance import pending_trade_reason, loss_lock_reason

_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], tuple[int, pd.DataFrame]] = {}
ENTRY_START = 20
ENTRY_END = 25


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _minute_start(now: datetime) -> datetime:
    return now.replace(second=0, microsecond=0)


def _current_tick_price(payload: dict) -> float:
    for key in ("mid", "price", "last", "bid", "ask"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    bid, ask = payload.get("bid"), payload.get("ask")
    if isinstance(bid, (int, float)) and isinstance(ask, (int, float)):
        return (float(bid) + float(ask)) / 2.0
    raise RuntimeError("BiQuote latest price unavailable")


def _tick_time(payload: dict, now: datetime) -> datetime:
    for key in ("timestamp", "time", "serverTime"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            ts = pd.to_datetime(value, utc=True, errors="coerce")
            if not pd.isna(ts):
                return ts.to_pydatetime().astimezone(timezone.utc)
        except Exception:
            pass
    return now


def _append_running_forex(frame: pd.DataFrame, pair: str, now: datetime) -> pd.DataFrame:
    tick = fetch_latest_tick(pair)
    price = _current_tick_price(tick)
    tick_time = _tick_time(tick, now)
    start = _minute_start(now)
    if tick_time < start:
        tick_time = now
    out = frame.copy() if frame is not None else pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    timestamps = pd.to_datetime(out.get("timestamp", pd.Series(dtype=object)), utc=True, errors="coerce")
    current = out.loc[timestamps == pd.Timestamp(start)] if not out.empty else pd.DataFrame()
    if current.empty:
        row = {"timestamp": pd.Timestamp(start), "open": price, "high": price, "low": price, "close": price}
        out = pd.concat([out, pd.DataFrame([row])], ignore_index=True)
    else:
        idx = current.index[-1]
        out.loc[idx, "high"] = max(float(out.loc[idx, "high"]), price)
        out.loc[idx, "low"] = min(float(out.loc[idx, "low"]), price)
        out.loc[idx, "close"] = price
    return out.sort_values("timestamp").reset_index(drop=True)


def _running_frame(pair: str, mode: str, now: datetime) -> pd.DataFrame:
    key = (mode, pair)
    period = int(now.timestamp()) // 60
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] == period:
            base = cached[1]
        else:
            base = fetch_crypto_running_candle(pair) if mode == "crypto" else fetch_forex_candles(pair, "1min")
            _CACHE[key] = (period, base)
    if mode == "crypto":
        return base
    return _append_running_forex(base, pair, now)


def _bd(dt: datetime) -> datetime:
    return dt.astimezone(timezone(timedelta(hours=6)))


def get_running_signal(pair: str, market_mode: str = "real") -> dict:
    pair = pair.strip().upper()
    mode = market_mode.strip().lower()
    if mode not in {"real", "crypto"}:
        raise ValueError("Unsupported market mode")
    if not pair:
        raise ValueError("No market selected")
    now = _now()
    sec = now.second
    if sec < ENTRY_START:
        return {"ok": True, "eligible": False, "signal": "WAIT", "pair": pair, "market_mode": mode,
                "seconds_until_entry_window": ENTRY_START - sec, "seconds_left_in_window": 0,
                "signal_time_utc": now.isoformat(timespec="seconds"),
                "message": f"Running analysis চলছে। Entry window {ENTRY_START:02d}-{ENTRY_END:02d} সেকেন্ডে।"}
    if sec > ENTRY_END:
        return {"ok": True, "eligible": False, "signal": "NO_ENTRY", "pair": pair, "market_mode": mode,
                "seconds_until_entry_window": 60 - sec + ENTRY_START, "seconds_left_in_window": 0,
                "signal_time_utc": now.isoformat(timespec="seconds"),
                "message": "এই 1-minute candle-এর entry window শেষ। পরের candle-এর 20-25s window অপেক্ষা করুন।"}

    pending = pending_trade_reason(mode, pair)
    if pending:
        return {"ok": True, "eligible": True, "signal": "NO_TRADE", "pair": pair, "market_mode": mode,
                "signal_time_utc": now.isoformat(timespec="seconds"), "entry_time_utc": now.isoformat(timespec="seconds"),
                "entry_time_bd": _bd(now).strftime("%d %b %Y, %H:%M:%S"), "entry_seconds_remaining": 60 - sec,
                "reason": pending}

    frame = _running_frame(pair, mode, now)
    result = generate_signal(frame)
    level_info = level_for_side(frame, result.action) if result.action in {"BUY", "SELL"} else None
    loss_reason = loss_lock_reason(mode, pair, result.action, frame, level_info)
    if loss_reason and result.action in {"BUY", "SELL"}:
        result = Signal("NO_TRADE", result.buy_score, result.sell_score, loss_reason)
        level_info = None
    if result.action in {"BUY", "SELL"}:
        block_reason = check_reentry_guard(frame, mode, pair, result.action)
        if block_reason:
            result = Signal("NO_TRADE", result.buy_score, result.sell_score, block_reason)
            level_info = None

    row = frame.iloc[-1]
    price = float(row["close"])
    candle_start = _minute_start(now)
    candle_end = candle_start + timedelta(minutes=1)
    action = result.action
    reason = str(result.reason or "")
    if action in {"BUY", "SELL"}:
        reason = f"{reason} Running 1M candle analysis থেকে {sec}s-এ entry। Entry window: {ENTRY_START}-{ENTRY_END}s; 30s-এর পরে নতুন entry বন্ধ।"
    return {"ok": True, "eligible": True, "pair": pair, "market_mode": mode,
            "source": "Binance" if mode == "crypto" else "BiQuote", "signal": action,
            "buy_score": result.buy_score, "sell_score": result.sell_score, "reason": reason,
            "signal_time_utc": now.isoformat(timespec="seconds"), "signal_time_bd": _bd(now).strftime("%d %b %Y, %H:%M:%S"),
            "candle_time": candle_start.isoformat(timespec="seconds"), "analysis_candle_time_utc": candle_start.isoformat(timespec="seconds"),
            "entry_price": price, "entry_price_type": "running_1m_price", "entry_time_utc": now.isoformat(timespec="seconds"),
            "entry_time_bd": _bd(now).strftime("%d %b %Y, %H:%M:%S"), "entry_seconds_remaining": max(0, int((candle_end - now).total_seconds())),
            "expiry_time_utc": candle_end.isoformat(timespec="seconds"), "expiry_time_bd": _bd(candle_end).strftime("%d %b %Y, %H:%M:%S"),
            "timeframe": "Running MMC / 1m", "entry_timeframe": "current 1m candle", "entry_window": "20-25 seconds",
            "mmc_level_type": level_info[0] if level_info else None, "mmc_level_price": level_info[1] if level_info else None}
