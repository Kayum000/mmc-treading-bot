"""Persistent 1-minute candle-color performance for the active tick-run strategy."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

from data.biquote_forex import fetch_forex_candles

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
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _minute_start(value: str | datetime) -> datetime:
    return _utc(value).replace(second=0, microsecond=0)


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
                    mmc_level_type VARCHAR(16),
                    mmc_level_price DOUBLE PRECISION,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    resolved_at TIMESTAMPTZ,
                    UNIQUE (market_mode, pair, signal, entry_time_utc)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS mmc_signal_performance_signal_time_idx
                ON mmc_signal_performance (signal_time_utc DESC)
            """)
            cur.execute("DELETE FROM mmc_signal_performance WHERE signal_time_utc < NOW() - INTERVAL '24 hours'")
        conn.commit()


def record_signal(result: dict) -> None:
    """Record one unique 1-minute BUY/SELL decision for its NEXT candle."""
    signal = str(result.get("signal", "")).upper()
    if signal not in {"BUY", "SELL"}:
        return
    try:
        init_db()
        signal_time = _utc(result["signal_time_utc"])
        entry_time = _minute_start(result.get("entry_time_utc") or (signal_time + timedelta(minutes=1)))
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO mmc_signal_performance
                        (market_mode, pair, signal, signal_time_utc, entry_time_utc,
                         entry_price_reference, reason, mmc_level_type, mmc_level_price)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (market_mode, pair, signal, entry_time_utc) DO NOTHING
                """, (
                    result.get("market_mode", "real"), result.get("pair", ""), signal,
                    signal_time, entry_time, result.get("entry_price"), result.get("reason"),
                    None, None,
                ))
            conn.commit()
    except Exception:
        return


def _entry_candle(frame, entry_time: datetime):
    if frame is None or frame.empty:
        return None
    target = _minute_start(entry_time)
    timestamps = frame["timestamp"].apply(_minute_start)
    matches = frame.loc[timestamps == target]
    return matches.iloc[-1] if not matches.empty else None


def _candle_color(candle) -> str | None:
    """Return the candle's directional color from its OHLC values."""
    if candle is None:
        return None
    opening = float(candle["open"])
    closing = float(candle["close"])
    if closing > opening:
        return "GREEN"
    if closing < opening:
        return "RED"
    return "DOJI"


def _outcome(signal: str, candle) -> str | None:
    """Evaluate strictly from the SIGNAL'S entry candle color."""
    color = _candle_color(candle)
    if color is None:
        return None
    if color == "DOJI":
        return "VOID"
    if signal == "BUY":
        return "WIN" if color == "GREEN" else "LOSS"
    if signal == "SELL":
        return "WIN" if color == "RED" else "LOSS"
    return None


def settle_pending() -> None:
    """Resolve each due signal using the exact NEXT 1-minute entry candle."""
    init_db()
    now = datetime.now(timezone.utc)
    frames = {}
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, market_mode, pair, signal, entry_time_utc
                FROM mmc_signal_performance
                WHERE result='PENDING'
                  AND entry_time_utc + INTERVAL '1 minute' <= %s
                  AND signal_time_utc >= %s
                ORDER BY entry_time_utc ASC
            """, (now, now - RETENTION))
            rows = cur.fetchall()
            for row_id, mode, pair, signal, entry_time in rows:
                if mode != "real":
                    continue
                key = (mode, pair)
                if key not in frames:
                    try:
                        frames[key] = fetch_forex_candles(pair, "1min", outputsize=200)
                    except Exception:
                        frames[key] = None
                candle = _entry_candle(frames[key], entry_time)
                outcome = _outcome(signal, candle)
                if outcome is None:
                    continue
                color = _candle_color(candle)
                cur.execute("""
                    UPDATE mmc_signal_performance
                    SET entry_price_actual=%s,
                        result_price=%s,
                        result=%s,
                        reason=COALESCE(reason,'') || %s,
                        resolved_at=%s
                    WHERE id=%s AND result='PENDING'
                """, (
                    float(candle["open"]), float(candle["close"]), outcome,
                    f" Entry candle color: {color}; candle={_minute_start(entry_time).isoformat()}; open={float(candle['open'])}; close={float(candle['close'])}.",
                    now, row_id,
                ))
            cur.execute("DELETE FROM mmc_signal_performance WHERE signal_time_utc < NOW() - INTERVAL '24 hours'")
        conn.commit()


def clear_performance_history() -> dict:
    """Clear confirmed result history only."""
    try:
        init_db()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM mmc_signal_performance WHERE result IN ('WIN','LOSS','VOID')")
                cleared = cur.rowcount
            conn.commit()
        return {"ok": True, "cleared": int(cleared)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_performance() -> dict:
    try:
        settle_pending()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FILTER (WHERE result IN ('WIN','LOSS')),
                           COUNT(*) FILTER (WHERE result='WIN'),
                           COUNT(*) FILTER (WHERE result='LOSS')
                    FROM mmc_signal_performance
                    WHERE signal_time_utc >= NOW() - INTERVAL '24 hours'
                      AND market_mode='real'
                """)
                total, wins, losses = [int(x or 0) for x in cur.fetchone()]
                accuracy = (wins / total * 100.0) if total else 0.0
                cur.execute("""
                    SELECT id, market_mode, pair, signal, signal_time_utc, entry_time_utc,
                           entry_price_actual, result_price, result
                    FROM mmc_signal_performance
                    WHERE signal_time_utc >= NOW() - INTERVAL '24 hours'
                      AND market_mode='real'
                      AND result IN ('WIN','LOSS')
                    ORDER BY signal_time_utc DESC LIMIT 50
                """)
                history = []
                for row in cur.fetchall():
                    history.append({
                        "id": int(row[0]), "market_mode": row[1], "pair": row[2],
                        "signal": row[3], "signal_time_utc": row[4].isoformat(),
                        "entry_time_utc": row[5].isoformat(),
                        "entry_price": float(row[6]) if row[6] is not None else None,
                        "result_price": float(row[7]) if row[7] is not None else None,
                        "result": row[8],
                    })
        return {
            "ok": True,
            "total": total,
            "wins": wins,
            "losses": losses,
            "accuracy": round(accuracy, 2),
            "win_rate": round(accuracy, 2),
            "history": history,
            "timeframe": "1m",
            "evaluation": "entry candle (the next 1-minute candle after signal)",
            "strategy": "tick_run_pressure",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
