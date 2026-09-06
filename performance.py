"""Persistent 24-hour performance and exact one-loss protection for clean MMC."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

from data.twelve_data_forex import fetch_forex_candles
from data.binance_crypto import fetch_crypto_candles, fetch_crypto_candle_at
from strategy.mmc import level_for_side, final_confirmation

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
            cur.execute("ALTER TABLE mmc_signal_performance ADD COLUMN IF NOT EXISTS mmc_level_type VARCHAR(16)")
            cur.execute("ALTER TABLE mmc_signal_performance ADD COLUMN IF NOT EXISTS mmc_level_price DOUBLE PRECISION")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS mmc_signal_performance_signal_time_idx
                ON mmc_signal_performance (signal_time_utc DESC)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mmc_loss_locks (
                    market_mode VARCHAR(16) NOT NULL,
                    pair VARCHAR(32) NOT NULL,
                    loss_signal VARCHAR(8) NOT NULL CHECK (loss_signal IN ('BUY','SELL')),
                    loss_entry_time_utc TIMESTAMPTZ NOT NULL,
                    loss_level_type VARCHAR(16),
                    loss_level_price DOUBLE PRECISION,
                    waiting_for_new_level BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (market_mode, pair)
                )
            """)
            cur.execute("ALTER TABLE mmc_loss_locks ADD COLUMN IF NOT EXISTS loss_level_type VARCHAR(16)")
            cur.execute("ALTER TABLE mmc_loss_locks ADD COLUMN IF NOT EXISTS loss_level_price DOUBLE PRECISION")
            cur.execute("ALTER TABLE mmc_loss_locks ADD COLUMN IF NOT EXISTS waiting_for_new_level BOOLEAN NOT NULL DEFAULT TRUE")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS mmc_loss_locks_created_idx
                ON mmc_loss_locks (created_at DESC)
            """)
            cur.execute("DELETE FROM mmc_signal_performance WHERE signal_time_utc < NOW() - INTERVAL '24 hours'")
        conn.commit()


def _get_loss_lock(mode: str, pair: str):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT loss_signal, loss_entry_time_utc, loss_level_type, loss_level_price, waiting_for_new_level
                FROM mmc_loss_locks WHERE market_mode=%s AND pair=%s
            """, (mode, pair))
            return cur.fetchone()


def _clear_loss_lock(mode: str, pair: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mmc_loss_locks WHERE market_mode=%s AND pair=%s", (mode, pair))
        conn.commit()


def loss_lock_reason(mode: str, pair: str, signal_action: str, frame=None, level_info=None) -> str | None:
    """After one LOSS, allow a signal only on a new strong level + fresh MMC confirmation."""
    action = str(signal_action).upper()
    if action not in {"BUY", "SELL", "NO_TRADE"}:
        return None
    try:
        init_db()
        lock = _get_loss_lock(mode, pair)
        if not lock:
            return None
        loss_signal, loss_entry_time, old_type, old_price, waiting_for_new_level = lock

        if action in {"BUY", "SELL"} and frame is not None and level_info is not None:
            new_type, new_price = level_info
            same_old_level = (
                old_type == new_type and old_price is not None and
                abs(float(new_price) - float(old_price)) <= max(abs(float(old_price)) * 0.0005, 1e-12)
            )
            fresh_confirmation = final_confirmation(frame, action.lower())
            if not same_old_level and fresh_confirmation:
                _clear_loss_lock(mode, pair)
                return None

        if action in {"BUY", "SELL"}:
            return (
                f"LOSS_LOCKED: {mode.upper()} {pair}-এ সর্বশেষ {loss_signal} entry LOSS হয়েছে "
                f"({_minute_start(loss_entry_time).isoformat()})। নতুন strong level এবং fresh MMC confirmation "
                "একসাথে না আসা পর্যন্ত signal OFF থাকবে।"
            )
        return None
    except Exception:
        if action in {"BUY", "SELL"}:
            return "LOSS_LOCKED: loss-protection state যাচাই করা যায়নি; নিরাপত্তার জন্য signal OFF রাখা হয়েছে।"
        return None


def pending_trade_reason(mode: str, pair: str) -> str | None:
    try:
        init_db()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT signal, entry_time_utc FROM mmc_signal_performance
                    WHERE market_mode=%s AND pair=%s AND result='PENDING'
                    ORDER BY entry_time_utc ASC LIMIT 1
                """, (mode, pair))
                row = cur.fetchone()
        if not row:
            return None
        signal, entry_time = row
        return (
            f"PENDING_LOCK: এই {mode.upper()} {pair} market-এ আগের {signal} entry এখনো settle হয়নি "
            f"({_minute_start(entry_time).isoformat()})। আগের 1-minute candle-এর WIN/LOSS নিশ্চিত না হওয়া পর্যন্ত নতুন BUY/SELL বন্ধ।"
        )
    except Exception:
        return "PENDING_LOCK: performance state যাচাই করা যায়নি; নিরাপত্তার জন্য নতুন BUY/SELL সাময়িকভাবে বন্ধ।"


def record_signal(result: dict) -> None:
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
                         entry_price_reference, reason, mmc_level_type, mmc_level_price)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (market_mode, pair, signal, entry_time_utc) DO NOTHING
                """, (
                    result.get("market_mode", "real"), result.get("pair", ""), signal,
                    _utc(result["signal_time_utc"]), _minute_start(result["entry_time_utc"]),
                    result.get("entry_price"), result.get("reason"),
                    result.get("mmc_level_type"), result.get("mmc_level_price"),
                ))
            conn.commit()
    except Exception:
        return


def _frame_for_market(mode: str, pair: str):
    if mode == "crypto":
        return fetch_crypto_candles(pair.replace("/", ""), "1m", limit=200)
    return fetch_forex_candles(pair, "1min", outputsize=2000)


def _candle_from_frame(frame, entry_time: datetime, mode: str | None = None, pair: str | None = None):
    if frame is not None and not frame.empty:
        target = _minute_start(entry_time)
        timestamps = frame["timestamp"].apply(_minute_start)
        matches = frame.loc[timestamps == target]
        if not matches.empty:
            return matches.iloc[-1]
    # A pending entry can be older than the normal live-data window. Fetch only
    # the exact historical candle needed for settlement instead of incorrectly
    # leaving the trade PENDING forever.
    if mode == "crypto" and pair:
        try:
            historical = fetch_crypto_candle_at(pair.replace("/", ""), entry_time)
            if historical is not None and not historical.empty:
                return historical.iloc[-1]
        except Exception:
            return None
    return None


def _candle_color(candle) -> str:
    candle_open, candle_close = float(candle["open"]), float(candle["close"])
    return "GREEN" if candle_close > candle_open else "RED" if candle_close < candle_open else "DOJI"


def _outcome_from_color(signal: str, candle_color: str) -> str | None:
    if candle_color == "GREEN":
        return "WIN" if signal == "BUY" else "LOSS"
    if candle_color == "RED":
        return "WIN" if signal == "SELL" else "LOSS"
    return None


def settle_pending() -> None:
    """Resolve due entries from the exact next 1m candle's completed color."""
    init_db()
    now = datetime.now(timezone.utc)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, market_mode, pair, signal, entry_time_utc,
                       mmc_level_type, mmc_level_price
                FROM mmc_signal_performance
                WHERE result='PENDING' AND entry_time_utc <= %s
                  AND signal_time_utc >= %s
                ORDER BY entry_time_utc ASC
            """, (now, now - RETENTION))
            rows = cur.fetchall()
            frames = {}
            for row_id, mode, pair, signal, entry_time, level_type, level_price in rows:
                key = (mode, pair)
                if key not in frames:
                    try:
                        frames[key] = _frame_for_market(mode, pair)
                    except Exception:
                        frames[key] = None
                entry_time = _minute_start(entry_time)
                candle = _candle_from_frame(frames[key], entry_time, mode, pair)
                if candle is None:
                    continue
                outcome = _outcome_from_color(signal, _candle_color(candle))
                if outcome is None:
                    continue
                candle_color = _candle_color(candle)
                cur.execute("""
                    UPDATE mmc_signal_performance
                    SET entry_price_actual=%s, result_price=%s, result=%s,
                        reason=COALESCE(reason,'') || %s, resolved_at=%s
                    WHERE id=%s AND result='PENDING'
                """, (
                    float(candle["open"]), float(candle["close"]), outcome,
                    f" Result candle color: {candle_color}.", now, row_id,
                ))
                if outcome == "LOSS":
                    cur.execute("""
                        INSERT INTO mmc_loss_locks
                            (market_mode, pair, loss_signal, loss_entry_time_utc,
                             loss_level_type, loss_level_price, waiting_for_new_level)
                        VALUES (%s,%s,%s,%s,%s,%s,TRUE)
                        ON CONFLICT (market_mode, pair) DO UPDATE SET
                            loss_signal=EXCLUDED.loss_signal,
                            loss_entry_time_utc=EXCLUDED.loss_entry_time_utc,
                            loss_level_type=EXCLUDED.loss_level_type,
                            loss_level_price=EXCLUDED.loss_level_price,
                            waiting_for_new_level=TRUE,
                            created_at=NOW()
                    """, (mode, pair, signal, entry_time, level_type, level_price))
            cur.execute("DELETE FROM mmc_signal_performance WHERE signal_time_utc < NOW() - INTERVAL '24 hours'")
        conn.commit()


def get_performance() -> dict:
    try:
        settle_pending()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT signal, COUNT(*) FILTER (WHERE result IN ('WIN','LOSS')),
                           COUNT(*) FILTER (WHERE result='WIN'), COUNT(*) FILTER (WHERE result='LOSS')
                    FROM mmc_signal_performance
                    WHERE signal_time_utc >= NOW() - INTERVAL '24 hours'
                    GROUP BY signal ORDER BY signal
                """)
                by_signal = {r[0]: {"total": int(r[1]), "wins": int(r[2]), "losses": int(r[3])} for r in cur.fetchall()}
                cur.execute("""
                    SELECT COUNT(*) FILTER (WHERE result IN ('WIN','LOSS')),
                           COUNT(*) FILTER (WHERE result='WIN'), COUNT(*) FILTER (WHERE result='LOSS')
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
                    ORDER BY signal_time_utc DESC LIMIT 50
                """)
                history = [
                    {"id": int(r[0]), "market_mode": r[1], "pair": r[2], "signal": r[3],
                     "signal_time_utc": _utc(r[4]).isoformat(timespec="seconds"),
                     "entry_time_utc": _utc(r[5]).isoformat(timespec="seconds"),
                     "entry_price": r[6], "result_price": r[7], "result": r[8]}
                    for r in cur.fetchall()
                ]
        rate = round((wins / (wins + losses)) * 100, 2) if wins + losses else 0.0
        return {"ok": True, "total": total, "wins": wins, "losses": losses,
                "win_rate": rate, "by_signal": by_signal, "history": history, "window": "24h"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
