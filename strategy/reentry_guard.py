"""Guard against repeated entries from the same strong support/resistance level.

This guard is intentionally separate from the MMC signal rules. It only blocks a
new BUY/SELL when a previous strong-level signal for the same market/direction is
still tied to the same level and that level has not been invalidated. If the
persistent database is unavailable, the guard fails open so signal generation is
never broken by the protection layer.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

import pandas as pd


_LOOKBACK = 20
_TOLERANCE_FACTOR = 0.20


def _db_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is not configured")
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    return value


def _connect():
    import psycopg2
    return psycopg2.connect(_db_url(), connect_timeout=5)


def _utc(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _minute_start(value) -> datetime:
    return _utc(value).replace(second=0, microsecond=0)


def _level_at_candle(frame: pd.DataFrame, candle_time: datetime, side: str):
    """Return the strong level immediately before a signal candle."""
    if frame is None or frame.empty or "timestamp" not in frame:
        return None

    target = _minute_start(candle_time)
    work = frame.copy()
    timestamps = work["timestamp"].apply(_minute_start)
    history = work.loc[timestamps < target]
    if len(history) < _LOOKBACK:
        return None

    prior = history.tail(_LOOKBACK)
    avg_range = float((prior["high"] - prior["low"]).mean())
    if avg_range <= 0:
        return None

    if side == "SELL":
        level = float(prior["high"].max())
    else:
        level = float(prior["low"].min())
    tolerance = max(avg_range * _TOLERANCE_FACTOR, 1e-12)
    return level, tolerance


def _latest_strong_signal(mode: str, pair: str, side: str):
    """Fetch the latest stored strong-level signal for this market/direction."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT signal_time_utc, entry_time_utc, reason
                FROM mmc_signal_performance
                WHERE market_mode=%s
                  AND pair=%s
                  AND signal=%s
                  AND signal_time_utc >= NOW() - INTERVAL '24 hours'
                  AND (
                      reason LIKE '%%শক্তিশালী resistance rejection%%'
                      OR reason LIKE '%%শক্তিশালী support rejection%%'
                  )
                ORDER BY signal_time_utc DESC
                LIMIT 1
                """,
                (mode, pair, side),
            )
            return cur.fetchone()


def check_reentry_guard(frame: pd.DataFrame, mode: str, pair: str, side: str) -> str | None:
    """Return a block reason when the same strong level is still active.

    The previous signal's level is reconstructed from candles that existed before
    that signal. A later signal is blocked only while price remains on the same
    side of that level and the level has not been broken/invalidated. Once the
    level is genuinely broken, a fresh setup may trade again.
    """
    side = str(side).upper()
    if side not in {"BUY", "SELL"}:
        return None

    try:
        previous = _latest_strong_signal(mode, pair, side)
        if not previous:
            return None

        _, previous_entry_time, _ = previous
        previous_analysis_time = _minute_start(previous_entry_time) - timedelta(minutes=1)
        previous_info = _level_at_candle(frame, previous_analysis_time, side)
        if previous_info is None:
            return None
        previous_level, previous_tolerance = previous_info

        if frame is None or frame.empty:
            return None
        latest = frame.iloc[-1]
        latest_close = float(latest["close"])

        # A resistance is invalidated by a decisive close above it; support is
        # invalidated by a decisive close below it. Until that happens, repeated
        # entries from the same level are blocked.
        if side == "SELL":
            if latest_close > previous_level + previous_tolerance:
                return None
            return (
                "REENTRY_BLOCKED: একই strong resistance level থেকে আগের SELL signal "
                "ইতিমধ্যে দেওয়া হয়েছে; level invalidated না হওয়া পর্যন্ত নতুন SELL entry বন্ধ।"
            )

        if latest_close < previous_level - previous_tolerance:
            return None
        return (
            "REENTRY_BLOCKED: একই strong support level থেকে আগের BUY signal "
            "ইতিমধ্যে দেওয়া হয়েছে; level invalidated না হওয়া পর্যন্ত নতুন BUY entry বন্ধ।"
        )
    except Exception:
        # The protection layer must never make the live signal endpoint fail.
        return None
