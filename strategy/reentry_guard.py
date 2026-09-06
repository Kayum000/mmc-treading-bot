"""Persistent one-entry lock for each active MMC support/resistance level."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd

from strategy.mmc_clean import strong_level_rejection

_LOOKBACK = 20
_TOLERANCE_FACTOR = 0.08


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


def _level_before_latest(frame: pd.DataFrame, side: str):
    if frame is None or frame.empty or "timestamp" not in frame:
        return None
    work = frame.copy()
    timestamps = work["timestamp"].apply(_minute_start)
    prior = work.loc[timestamps < timestamps.iloc[-1]].tail(_LOOKBACK)
    if len(prior) < _LOOKBACK:
        return None
    avg_range = float((prior["high"] - prior["low"]).median())
    if avg_range <= 0:
        return None
    level = float(prior["high"].max()) if side == "SELL" else float(prior["low"].min())
    tolerance = max(avg_range * _TOLERANCE_FACTOR, 1e-12)
    return level, tolerance


def _ensure_table() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mmc_active_level_locks (
                    market_mode VARCHAR(16) NOT NULL,
                    pair VARCHAR(32) NOT NULL,
                    side VARCHAR(8) NOT NULL CHECK (side IN ('BUY','SELL')),
                    level_type VARCHAR(16) NOT NULL,
                    level_price DOUBLE PRECISION NOT NULL,
                    tolerance DOUBLE PRECISION NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (market_mode, pair, side)
                )
            """)
        conn.commit()


def _get_lock(mode: str, pair: str, side: str):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT level_type, level_price, tolerance
                FROM mmc_active_level_locks
                WHERE market_mode=%s AND pair=%s AND side=%s
            """, (mode, pair, side))
            return cur.fetchone()


def _delete_lock(mode: str, pair: str, side: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM mmc_active_level_locks
                WHERE market_mode=%s AND pair=%s AND side=%s
            """, (mode, pair, side))
        conn.commit()


def _save_lock(mode: str, pair: str, side: str, level_type: str, level_price: float, tolerance: float) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO mmc_active_level_locks
                    (market_mode, pair, side, level_type, level_price, tolerance)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (market_mode, pair, side) DO UPDATE SET
                    level_type=EXCLUDED.level_type,
                    level_price=EXCLUDED.level_price,
                    tolerance=EXCLUDED.tolerance,
                    created_at=NOW()
            """, (mode, pair, side, level_type, level_price, tolerance))
        conn.commit()


def check_reentry_guard(frame: pd.DataFrame, mode: str, pair: str, side: str) -> str | None:
    """Block repeated entries while the same MMC level remains valid."""
    side = str(side).upper()
    if side not in {"BUY", "SELL"}:
        return None
    try:
        _ensure_table()
        lock = _get_lock(mode, pair, side)
        if lock:
            level_type, level_price, tolerance = lock
            if frame is not None and not frame.empty:
                latest_close = float(frame.iloc[-1]["close"])
                invalidated = (
                    latest_close > float(level_price) + float(tolerance)
                    if side == "SELL"
                    else latest_close < float(level_price) - float(tolerance)
                )
                if invalidated:
                    _delete_lock(mode, pair, side)
                else:
                    return (
                        f"REENTRY_BLOCKED: একই active strong {level_type} level থেকে আগের {side} signal ইতিমধ্যে দেওয়া হয়েছে; "
                        "level invalidated না হওয়া পর্যন্ত নতুন entry বন্ধ।"
                    )

        expected = "strong_support_rejection" if side == "BUY" else "strong_resistance_rejection"
        if strong_level_rejection(frame) != expected:
            return None
        info = _level_before_latest(frame, side)
        if info is None:
            return None
        level_price, tolerance = info
        _save_lock(mode, pair, side, "support" if side == "BUY" else "resistance", level_price, tolerance)
        return None
    except Exception:
        return None
