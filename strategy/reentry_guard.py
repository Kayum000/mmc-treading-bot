"""Persistent one-entry lock for each active clean MMC level."""
from __future__ import annotations

import os

import pandas as pd

from strategy.mmc import get_mmc_levels, strong_level_rejection


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
    """Allow one entry per level; unlock only after invalidation or a fresh level."""
    side = str(side).upper()
    if side not in {"BUY", "SELL"}:
        return None
    try:
        _ensure_table()
        lock = _get_lock(mode, pair, side)

        levels = get_mmc_levels(frame)
        current_level = None
        current_tolerance = None
        if levels is not None:
            if side == "BUY":
                current_level = levels.get("support")
            else:
                current_level = levels.get("resistance")
            current_tolerance = float(levels.get("tolerance") or 0)

        if lock:
            level_type, level_price, tolerance = lock
            fresh_level = (
                current_level is not None
                and abs(float(current_level) - float(level_price)) > max(float(tolerance), current_tolerance or 0.0) * 1.5
            )
            invalidated = False
            if frame is not None and not frame.empty:
                latest_close = float(frame.iloc[-1]["close"])
                invalidated = (
                    latest_close > float(level_price) + float(tolerance)
                    if side == "SELL"
                    else latest_close < float(level_price) - float(tolerance)
                )

            if invalidated or fresh_level:
                _delete_lock(mode, pair, side)
            else:
                return (
                    f"REENTRY_BLOCKED: একই active strong {level_type} level থেকে আগের {side} signal দেওয়া হয়েছে; "
                    "level invalidated বা নতুন strong level তৈরি না হওয়া পর্যন্ত নতুন entry বন্ধ।"
                )

        expected = "strong_support_rejection" if side == "BUY" else "strong_resistance_rejection"
        if strong_level_rejection(frame) != expected or levels is None or current_level is None:
            return None

        _save_lock(
            mode,
            pair,
            side,
            "support" if side == "BUY" else "resistance",
            float(current_level),
            float(current_tolerance or levels["tolerance"]),
        )
        return None
    except Exception:
        return None
