"""Persistent 24-hour signal performance tracking.

Only confirmed BUY/SELL signals are stored. Results are evaluated from the
exact next 1-minute candle after that candle has fully closed.

A LOSS also creates a persistent market/pair lock. The lock is cleared only
after a later signal check produces NO_TRADE (meaning the previous setup has
fully disappeared); only a subsequent fresh valid MMC setup can then signal.
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


def _minute_start(value: str | datetime) -> datetime:
    """Normalize a timestamp to the exact UTC 1-minute candle start."""
    dt = _utc(value)
    return dt.replace(second=0, microsecond=0)


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
                CREATE TABLE IF NOT EXISTS mmc_loss_locks (
                    market_mode VARCHAR(16) NOT NULL,
                    pair VARCHAR(32) NOT NULL,
                    loss_signal VARCHAR(8) NOT NULL CHECK (loss_signal IN ('BUY','SELL')),
                    loss_entry_time_utc TIMESTAMPTZ NOT NULL,
                    waiting_for_neutral BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (market_mode, pair)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS mmc_loss_locks_created_idx
                ON mmc_loss_locks (created_at DESC)
            """)
            cur.execute("""
                DELETE FROM mmc_signal_performance
                WHERE signal_time_utc < NOW() - INTERVAL '24 hours'
            """)
            cur.execute("""
                DELETE FROM mmc_loss_locks
                WHERE created_at < NOW() - INTERVAL '24 hours'
            """)
        conn.commit()


def _set_loss_lock(mode: str, pair: str, signal: str, entry_time_utc: datetime) -> None:
    """Persist a lock after a confirmed LOSS."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO mmc_loss_locks
                    (market_mode, pair, loss_signal, loss_entry_time_utc, waiting_for_neutral)
                VALUES (%s,%s,%s,%s,TRUE)
                ON CONFLICT (market_mode, pair) DO UPDATE SET
                    loss_signal=EXCLUDED.loss_signal,
                    loss_entry_time_utc=EXCLUDED.loss_entry_time_utc,
                    waiting_for_neutral=TRUE,
                    created_at=NOW()
            """, (mode, pair, signal, _minute_start(entry_time_utc)))
        conn.commit()


def _get_loss_lock(mode: str, pair: str):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT loss_signal, loss_entry_time_utc, waiting_for_neutral
                FROM mmc_loss_locks
                WHERE market_mode=%s AND pair=%s
            """, (mode, pair))
            return cur.fetchone()


def _clear_loss_lock(mode: str, pair: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM mmc_loss_locks
                WHERE market_mode=%s AND pair=%s
            """, (mode, pair))
        conn.commit()


def loss_lock_reason(mode: str, pair: str, signal_action: str) -> str | None:
    """Enforce LOSS -> neutral setup -> fresh valid setup sequencing.

    While locked, BUY/SELL is blocked. A later NO_TRADE observation clears the
    lock, proving that the losing setup is no longer active. That NO_TRADE call
    itself never becomes a trade; a later fresh valid setup may signal normally.
    """
    action = str(signal_action).upper()
    if action not in {"BUY", "SELL", "NO_TRADE"}:
        return None
    try:
        init_db()
        lock = _get_loss_lock(mode, pair)
        if not lock:
            return None

        loss_signal, loss_entry_time, waiting_for_neutral = lock
        if action == "NO_TRADE" and waiting_for_neutral:
            _clear_loss_lock(mode, pair)
            return None

        if action in {"BUY", "SELL"}:
            return (
                f"LOSS_LOCKED: এই {mode.upper()} {pair} market-এ সর্বশেষ "
                f"{loss_signal} entry LOSS হয়েছে ({_minute_start(loss_entry_time).isoformat()})। "
                "আগের setup পুরোপুরি শেষ হয়ে একটি NO TRADE state না আসা পর্যন্ত নতুন signal বন্ধ। "
                "তারপর নতুন valid MMC setup এলে signal দেওয়া হবে।"
            )
    except Exception:
        # Database protection must never break the live signal endpoint.
        return None
    return None


def pending_trade_reason(mode: str, pair: str) -> str | None:
    """Block new BUY/SELL generation while this market has an unresolved entry.

    This is intentionally checked before creating another automatic signal. It
    prevents a slow market-data response at the exact candle boundary from
    causing overlapping 1-minute entries and the consecutive-loss pattern that
    can otherwise appear in AUTO SIGNAL mode.
    """
    try:
        init_db()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT signal, entry_time_utc
                    FROM mmc_signal_performance
                    WHERE market_mode=%s AND pair=%s AND result='PENDING'
                    ORDER BY entry_time_utc ASC
                    LIMIT 1
                """, (mode, pair))
                row = cur.fetchone()
        if not row:
            return None
        signal, entry_time = row
        return (
            f"PENDING_LOCK: এই {mode.upper()} {pair} market-এ আগের {signal} "
            f"entry এখনো settle হয়নি ({_minute_start(entry_time).isoformat()})। "
            "আগের 1-minute candle-এর WIN/LOSS নিশ্চিত না হওয়া পর্যন্ত নতুন BUY/SELL বন্ধ।"
        )
    except Exception:
        # Preserve the existing fail-open behavior if PostgreSQL is unavailable.
        return None


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
                    _minute_start(result["entry_time_utc"]),
                    result.get("entry_price"),
                    result.get("reason"),
                ))
            conn.commit()
    except Exception:
        return


def _frame_for_market(mode: str, pair: str):
    if mode == "crypto":
        return fetch_crypto_candles(pair.replace("/", ""), "1m", limit=200)
    return fetch_forex_candles(pair, "1min", outputsize=200)


def _candle_from_frame(frame, entry_time: datetime):
    """Return only the candle whose START timestamp is exactly entry_time."""
    if frame is None or frame.empty:
        return None
    target = _minute_start(entry_time)
    timestamps = frame["timestamp"].apply(_minute_start)
    matches = frame.loc[timestamps == target]
    if matches.empty:
        return None
    return matches.iloc[-1]


def _candle_color(candle) -> str:
    """Classify the completed entry candle as GREEN, RED, or DOJI."""
    candle_open = float(candle["open"])
    candle_close = float(candle["close"])
    if candle_close > candle_open:
        return "GREEN"
    if candle_close < candle_open:
        return "RED"
    return "DOJI"


def _outcome_from_color(signal: str, candle_color: str) -> str | None:
    """Determine WIN/LOSS from candle color only; DOJI stays unresolved."""
    if candle_color == "GREEN":
        return "WIN" if signal == "BUY" else "LOSS"
    if candle_color == "RED":
        return "WIN" if signal == "SELL" else "LOSS"
    return None


def settle_pending() -> None:
    """Resolve due signals from the exact next 1m candle's color."""
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
                entry_time = _minute_start(entry_time)
                candle = _candle_from_frame(frames[key], entry_time)
                if candle is None:
                    continue

                candle_color = _candle_color(candle)
                outcome = _outcome_from_color(signal, candle_color)
                if outcome is None:
                    continue

                candle_open = float(candle["open"])
                candle_close = float(candle["close"])
                cur.execute("""
                    UPDATE mmc_signal_performance
                    SET entry_price_actual=%s, result_price=%s, result=%s,
                        reason=COALESCE(reason,'') || %s,
                        resolved_at=%s
                    WHERE id=%s AND result='PENDING'
                """, (
                    candle_open,
                    candle_close,
                    outcome,
                    f" Result candle color: {candle_color}.",
                    now,
                    row_id,
                ))

                if outcome == "LOSS":
                    # The loss lock is written in the same DB transaction as the
                    # result, so the loss cannot be resolved without protection.
                    cur.execute("""
                        INSERT INTO mmc_loss_locks
                            (market_mode, pair, loss_signal, loss_entry_time_utc, waiting_for_neutral)
                        VALUES (%s,%s,%s,%s,TRUE)
                        ON CONFLICT (market_mode, pair) DO UPDATE SET
                            loss_signal=EXCLUDED.loss_signal,
                            loss_entry_time_utc=EXCLUDED.loss_entry_time_utc,
                            waiting_for_neutral=TRUE,
                            created_at=NOW()
                    """, (mode, pair, signal, entry_time))

            cur.execute("""
                DELETE FROM mmc_signal_performance
                WHERE signal_time_utc < NOW() - INTERVAL '24 hours'
            """)
            cur.execute("""
                DELETE FROM mmc_loss_locks
                WHERE created_at < NOW() - INTERVAL '24 hours'
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
