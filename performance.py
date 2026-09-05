"""Persistent 24-hour signal performance tracking.

Only confirmed BUY/SELL signals are stored. Results are evaluated from the
actual next 1-minute candle after that candle has fully closed.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

from data.twelve_data_forex import fetch_forex_candles
from data.binance_crypto import fetch_crypto_candles

RETENTION = timedelta(hours=24)


def _db_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is not configured for Performance storage.")
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    return value


def _connect():
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("PostgreSQL driver is not installed.") from exc
    return psycopg2.connect(_db_url(), connect_timeout=8)


def _utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def init_db() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mmc_signal_performance (
                    id BIGSERIAL PRIMARY KEY,
                    market_mode VARCHAR(16) NOT NULL,
                    pair VARCHAR(32) NOT NULL,
                    signal VARCHAR(8) NOT NULL CHECK (signal IN ('BUY','SELL')),
                    signal_time_utc TIMESTAMPTZ NOT NULL,
                    entry_time_utc TIMESTAMPTZ NOT NULL,
                    entry_price_reference DOUBLE PRECISION,
                    entry_price_actual DOUBLE PRECISION,
                    result_price DOUBLE PRECISION,
                    result VARCHAR(16) NOT NULL DEFAULT 'PENDING',
                    reason TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    resolved_at TIMESTAMPTZ,
                    UNIQUE (market_mode, pair, signal, entry_time_utc)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS mmc_signal_performance_signal_time_idx
                ON mmc_signal_performance (signal_time_utc DESC)
            """)
            cur.execute("""
                DELETE FROM mmc_signal_performance
                WHERE signal_time_utc < NOW() - INTERVAL '24 hours'
            """)
        conn.commit()


def record_signal(result: dict) -> None:
    """Persist a BUY/SELL signal without ever breaking the live signal path."""
    signal = str(result.get("signal", "")).upper()
    if signal not in {"BUY", "SELL"}:
        return
    try:
        init_db()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO mmc_signal_performance
                        (market_mode, pair, signal, signal_time_utc, entry_time_utc,
                         entry_price_reference, reason)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (market_mode, pair, signal, entry_time_utc) DO NOTHING
                """, (
                    result.get("market_mode", "real"),
                    result.get("pair", ""),
                    signal,
                    _utc(result["signal_time_utc"]),
                    _utc(result["entry_time_utc"]),
                    result.get("entry_price"),
                    result.get("reason"),
                ))
            conn.commit()
    except Exception:
        # Performance is an add-on; DB/network problems must not break GET SIGNAL.
        return


def _frame_for_market(mode: str, pair: str):
    if mode == "crypto":
        return fetch_crypto_candles(pair.replace("/", ""), "1m", limit=200)
    return fetch_forex_candles(pair, "1min", outputsize=200)


def _candle_from_frame(frame, entry_time: datetime):
    if frame is None or frame.empty:
        return None
    target = entry_time.timestamp()
    stamps = frame["timestamp"].apply(lambda x: _utc(x).timestamp())
    matches = frame.loc[(stamps - target).abs() < 0.5]
    if matches.empty:
        return None
    return matches.iloc[-1]


def settle_pending() -> None:
    """Resolve due signals using one 1m data request per unique pending market."""
    init_db()
    now = datetime.now(timezone.utc)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, market_mode, pair, signal, entry_time_utc
                FROM mmc_signal_performance
                WHERE result = 'PENDING' AND entry_time_utc <= %s
                  AND signal_time_utc >= %s
                ORDER BY entry_time_utc ASC
            """, (now, now - RETENTION))
            rows = cur.fetchall()

            frames = {}
            for row_id, mode, pair, signal, entry_time in rows:
                key = (mode, pair)
                if key not in frames:
                    try:
                        frames[key] = _frame_for_market(mode, pair)
                    except Exception:
                        frames[key] = None
                candle = _candle_from_frame(frames[key], _utc(entry_time))
                if candle is None:
                    continue
                entry_price = float(candle["open"])
                result_price = float(candle["close"])
                if result_price > entry_price:
                    outcome = "WIN" if signal == "BUY" else "LOSS"
                elif result_price < entry_price:
                    outcome = "LOSS" if signal == "BUY" else "WIN"
                else:
                    # Do not invent a WIN/LOSS for an exact tie.
                    continue
                cur.execute("""
                    UPDATE mmc_signal_performance
                    SET entry_price_actual=%s, result_price=%s, result=%s,
                        resolved_at=%s
                    WHERE id=%s AND result='PENDING'
                """, (entry_price, result_price, outcome, now, row_id))

            cur.execute("""
                DELETE FROM mmc_signal_performance
                WHERE signal_time_utc < NOW() - INTERVAL '24 hours'
            """)
        conn.commit()


def get_performance() -> dict:
    try:
        settle_pending()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT signal, COUNT(*) FILTER (WHERE result IN ('WIN','LOSS')),
                           COUNT(*) FILTER (WHERE result='WIN'),
                           COUNT(*) FILTER (WHERE result='LOSS')
                    FROM mmc_signal_performance
                    WHERE signal_time_utc >= NOW() - INTERVAL '24 hours'
                    GROUP BY signal
                    ORDER BY signal
                """)
                by_signal = {r[0]: {"total": int(r[1]), "wins": int(r[2]), "losses": int(r[3])} for r in cur.fetchall()}
                cur.execute("""
                    SELECT COUNT(*) FILTER (WHERE result IN ('WIN','LOSS')),
                           COUNT(*) FILTER (WHERE result='WIN'),
                           COUNT(*) FILTER (WHERE result='LOSS')
                    FROM mmc_signal_performance
                    WHERE signal_time_utc >= NOW() - INTERVAL '24 hours'
                """)
                total, wins, losses = [int(x or 0) for x in cur.fetchone()]
                cur.execute("""
                    SELECT id, market_mode, pair, signal, signal_time_utc, entry_time_utc,
                           entry_price_actual, result_price, result
                    FROM mmc_signal_performance
                    WHERE signal_time_utc >= NOW() - INTERVAL '24 hours'
                      AND result IN ('WIN','LOSS')
                    ORDER BY signal_time_utc DESC
                    LIMIT 50
                """)
                history = []
                for r in cur.fetchall():
                    history.append({
                        "id": int(r[0]), "market_mode": r[1], "pair": r[2], "signal": r[3],
                        "signal_time_utc": _utc(r[4]).isoformat(timespec="seconds"),
                        "entry_time_utc": _utc(r[5]).isoformat(timespec="seconds"),
                        "entry_price": r[6], "result_price": r[7], "result": r[8],
                    })
        rate = round((wins / (wins + losses)) * 100, 2) if wins + losses else 0.0
        return {"ok": True, "total": total, "wins": wins, "losses": losses,
                "win_rate": rate, "by_signal": by_signal, "history": history,
                "window": "24h"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
