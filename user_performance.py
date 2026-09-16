"""Per-user view of the existing persistent signal performance table."""
from __future__ import annotations

from performance import record_signal as _record_signal
from performance import get_performance as _global_performance
from performance import clear_performance_history as _global_clear
from performance import _connect, init_db


def _init_links():
    init_db()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS mmc_user_signal_links (
                user_id BIGINT NOT NULL REFERENCES mmc_users(id) ON DELETE CASCADE,
                performance_id BIGINT NOT NULL REFERENCES mmc_signal_performance(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, performance_id)
            )""")
            cur.execute("CREATE INDEX IF NOT EXISTS mmc_user_signal_links_user_idx ON mmc_user_signal_links(user_id, created_at DESC)")
        conn.commit()


def record_signal(result, user_id=None):
    ok = _record_signal(result)
    if not ok or not user_id:
        return ok
    try:
        _init_links()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT id FROM mmc_signal_performance
                    WHERE market_mode=%s AND pair=%s AND signal=%s AND entry_time_utc=%s
                    ORDER BY id DESC LIMIT 1""", (result.get("market_mode", "real"), result.get("pair", ""), result.get("signal", ""), result.get("entry_time_utc") or result.get("signal_time_utc")))
                row = cur.fetchone()
                if row:
                    cur.execute("INSERT INTO mmc_user_signal_links (user_id,performance_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (int(user_id), int(row[0])))
            conn.commit()
    except Exception:
        pass
    return ok


def get_performance(user_id=None):
    if not user_id:
        return _global_performance()
    try:
        _init_links()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT COUNT(*) FILTER (WHERE p.result IN ('WIN','LOSS')),
                    COUNT(*) FILTER (WHERE p.result='WIN'), COUNT(*) FILTER (WHERE p.result='LOSS')
                    FROM mmc_signal_performance p JOIN mmc_user_signal_links l ON l.performance_id=p.id
                    WHERE l.user_id=%s AND p.signal_time_utc >= NOW()-INTERVAL '24 hours'""", (int(user_id),))
                total,wins,losses=[int(x or 0) for x in cur.fetchone()]
                accuracy=wins/total*100.0 if total else 0.0
                cur.execute("""SELECT p.id,p.market_mode,p.pair,p.signal,p.signal_time_utc,p.entry_time_utc,
                    p.entry_price_actual,p.result_price,p.result FROM mmc_signal_performance p
                    JOIN mmc_user_signal_links l ON l.performance_id=p.id
                    WHERE l.user_id=%s AND p.signal_time_utc >= NOW()-INTERVAL '24 hours'
                    AND p.result IN ('WIN','LOSS') ORDER BY p.signal_time_utc DESC LIMIT 50""", (int(user_id),))
                history=[{'id':int(r[0]),'market_mode':r[1],'pair':r[2],'signal':r[3],'signal_time_utc':r[4].isoformat(),'entry_time_utc':r[5].isoformat(),'entry_price':float(r[6]) if r[6] is not None else None,'result_price':float(r[7]) if r[7] is not None else None,'result':r[8]} for r in cur.fetchall()]
        return {'ok':True,'total':total,'wins':wins,'losses':losses,'accuracy':round(accuracy,2),'win_rate':round(accuracy,2),'history':history,'timeframe':'1m','evaluation':'signal entry candle','scope':'user'}
    except Exception as exc:
        return {'ok':False,'error':str(exc)}


def clear_performance_history(user_id=None):
    if not user_id:
        return _global_clear()
    try:
        _init_links()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""DELETE FROM mmc_signal_performance p USING mmc_user_signal_links l
                    WHERE p.id=l.performance_id AND l.user_id=%s AND p.result IN ('WIN','LOSS','VOID')""", (int(user_id),))
                cleared=cur.rowcount
            conn.commit()
        return {'ok':True,'cleared':int(cleared),'scope':'user'}
    except Exception as exc:
        return {'ok':False,'error':str(exc)}
