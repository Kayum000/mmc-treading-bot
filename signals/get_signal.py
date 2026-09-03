"""Live MMC signal generation for the selected Real or Crypto market."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import threading

from data.twelve_data_forex import fetch_forex_candles, fetch_forex_multi_timeframe
from data.binance_crypto import fetch_crypto_candles, fetch_crypto_multi_timeframe
from data.live_signal import build_signal
from strategy.signal import confirm_1m_entry

_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _next_candle_boundary_utc(now_utc: datetime, seconds: int = 60) -> datetime:
    epoch = int(now_utc.timestamp())
    next_epoch = ((epoch // seconds) + 1) * seconds
    return datetime.fromtimestamp(next_epoch, tz=timezone.utc)


def _period_start(now_utc: datetime, seconds: int) -> int:
    return (int(now_utc.timestamp()) // seconds) * seconds


def _load_all(pair: str, market_mode: str) -> dict:
    if market_mode == "crypto":
        return fetch_crypto_multi_timeframe(pair.replace("/", ""))
    return fetch_forex_multi_timeframe(pair)


def _load_auto_frames(pair: str, market_mode: str, now_utc: datetime) -> dict:
    """Refresh only MTF timeframes whose closed-candle period has changed."""
    key = (market_mode, pair)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)

    if cached is None:
        frames = _load_all(pair, market_mode)
        with _CACHE_LOCK:
            _CACHE[key] = {
                "frames": frames,
                "periods": {
                    "5m": _period_start(now_utc, 300),
                    "15m": _period_start(now_utc, 900),
                    "30m": _period_start(now_utc, 1800),
                },
                "entry_frame": None,
                "entry_period": None,
            }
        return frames

    frames = dict(cached["frames"])
    periods = dict(cached["periods"])
    specs = {
        "5m": (300, "5m"),
        "15m": (900, "15m"),
        "30m": (1800, "30m"),
    }
    for label, (seconds, interval) in specs.items():
        current_period = _period_start(now_utc, seconds)
        if periods.get(label) != current_period:
            if market_mode == "crypto":
                frames[label] = fetch_crypto_candles(pair.replace("/", ""), interval)
            else:
                api_interval = {"5m": "5min", "15m": "15min", "30m": "30min"}[label]
                frames[label] = fetch_forex_candles(pair, api_interval)
            periods[label] = current_period

    with _CACHE_LOCK:
        current = _CACHE.get(key, {})
        _CACHE[key] = {
            "frames": frames,
            "periods": periods,
            "entry_frame": current.get("entry_frame"),
            "entry_period": current.get("entry_period"),
        }
    return frames


def _load_1m_entry_frame(pair: str, market_mode: str, now_utc: datetime, automatic: bool):
    """Load 1m data for final entry confirmation.

    Automatic mode refreshes this once per new 5m setup window, keeping the
    extra 1m request bounded while the selected market remains the only market
    being analyzed. Manual requests always fetch fresh 1m candles.
    """
    key = (market_mode, pair)
    current_period = _period_start(now_utc, 300)

    if automatic:
        with _CACHE_LOCK:
            cached = _CACHE.get(key, {})
            entry_frame = cached.get("entry_frame")
            entry_period = cached.get("entry_period")
        if entry_frame is not None and entry_period == current_period:
            return entry_frame

    if market_mode == "crypto":
        entry_frame = fetch_crypto_candles(pair.replace("/", ""), "1m")
    else:
        entry_frame = fetch_forex_candles(pair, "1min")

    if automatic:
        with _CACHE_LOCK:
            cached = _CACHE.get(key, {})
            _CACHE[key] = {
                "frames": cached.get("frames", {}),
                "periods": cached.get("periods", {}),
                "entry_frame": entry_frame,
                "entry_period": current_period,
            }
    return entry_frame


def get_signal(pair: str, market_mode: str = "real", automatic: bool = False) -> dict:
    # Keep the user's selected market as the single source of truth.
    pair = pair.strip().upper()
    market_mode = market_mode.strip().lower()
    if market_mode not in {"real", "crypto"}:
        raise ValueError("Unsupported market mode")
    if not pair:
        raise ValueError("No market selected")

    requested_pair = pair
    signal_at_utc = datetime.now(timezone.utc)

    if automatic:
        frames = _load_auto_frames(requested_pair, market_mode, signal_at_utc)
    else:
        frames = _load_all(requested_pair, market_mode)

    # First decide direction from the unchanged 30m/15m/5m MMC engine.
    result = build_signal(frames)

    # Only a genuine MTF BUY/SELL candidate gets the additional 1m entry check.
    # This avoids spending a 1m API request when the higher-timeframe setup is
    # already NO_TRADE.
    entry_frame = None
    if result.action in {"BUY", "SELL"}:
        entry_frame = _load_1m_entry_frame(
            requested_pair, market_mode, signal_at_utc, automatic
        )
        result = confirm_1m_entry(result, entry_frame)

    # The actual trade is for the next 1-minute candle, never the running candle.
    next_candle_utc = _next_candle_boundary_utc(signal_at_utc, 60)

    latest = entry_frame if entry_frame is not None else frames.get("5m")
    entry_price = None
    candle_time = None
    entry_price_type = "last_closed_1m_close_reference" if entry_frame is not None else "last_closed_5m_close_reference"
    if latest is not None and not latest.empty:
        row = latest.iloc[-1]
        entry_price = float(row["close"])
        candle_time_utc = pd_timestamp_to_utc(row["timestamp"])
        candle_time = candle_time_utc.isoformat(timespec="seconds")

    signal_bd = signal_at_utc.astimezone(timezone(timedelta(hours=6)))
    entry_bd = next_candle_utc.astimezone(timezone(timedelta(hours=6)))

    return {
        "pair": requested_pair,
        "requested_pair": requested_pair,
        "market_mode": market_mode,
        "source": "Binance" if market_mode == "crypto" else "Twelve Data",
        "signal": result.action,
        "buy_score": result.buy_score,
        "sell_score": result.sell_score,
        "reason": result.reason,
        "signal_time_utc": signal_at_utc.isoformat(timespec="seconds"),
        "signal_time_bd": signal_bd.strftime("%d %b %Y, %H:%M:%S"),
        "candle_time": candle_time,
        "analysis_candle_time_utc": candle_time,
        "entry_price": entry_price,
        "entry_price_type": entry_price_type,
        "entry_time_utc": next_candle_utc.isoformat(timespec="seconds"),
        "entry_time_bd": entry_bd.strftime("%d %b %Y, %H:%M:%S"),
        "entry_delay_seconds": 0,
        "timeframe": "1m entry / 5m setup / 15m + 30m confirmation",
        "entry_timeframe": "1m",
        "automatic": automatic,
    }


def pd_timestamp_to_utc(value) -> datetime:
    """Convert a candle timestamp to an aware UTC datetime."""
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
