"""Web UI for Real Forex and Quotex OTC signal generation."""
from __future__ import annotations

import hmac
import os
import time
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, jsonify, render_template, request, redirect, url_for, session

from signals.get_signal import get_signal
from data.biquote_forex import fetch_api_usage, get_credit_usage
from data.news_direction import get_news_direction_for_pair
from data.news_events import get_weekly_news_events_for_pair
from data.all_news_events import get_all_news_events
from data.otc_markets import OTC_DISPLAY_PAIRS
from notifications.telegram import get_recent_chats, notify_signal, notify_signal_result, send_test_message, telegram_enabled

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY") or os.urandom(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "1") == "1",
)

REAL_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "GBP/CHF",
    "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY", "EUR/AUD", "GBP/AUD",
    "AUD/CAD", "NZD/CAD",
]
QUOTEX_OTC_PAIRS = list(OTC_DISPLAY_PAIRS)

PERFORMANCE_DB = Path(os.getenv("MMC_PERFORMANCE_DB") or (Path(__file__).resolve().parent.parent / "data" / "performance.sqlite3"))


class _PostgresPerformanceConnection:
    """Small DB-API adapter so the existing performance code works on SQLite or PostgreSQL."""
    backend = "postgres"

    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, params=()):
        from psycopg2.extras import DictCursor

        cursor = self._connection.cursor(cursor_factory=DictCursor)
        # The app's SQL uses SQLite-style qmark placeholders. Translate only
        # the placeholders; all user values still go through bound parameters.
        cursor.execute(sql.replace("?", "%s"), tuple(params or ()))
        return cursor

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def _performance_db():
    database_url = (os.getenv("MMC_PERFORMANCE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if database_url:
        import psycopg2

        raw = psycopg2.connect(database_url, connect_timeout=10)
        con = _PostgresPerformanceConnection(raw)
        try:
            columns = {
                row[0] for row in con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='performance'"
                ).fetchall()
            }
            required = {
                "id", "time", "pair", "signal", "entry_price", "candle_color",
                "signal_time_utc", "analysis_candle_time_utc", "result",
                "signal_created_utc", "signal_created_bd", "outcome_price",
                "outcome_candle_time_utc", "outcome_basis", "market_mode",
                "strategy", "regime", "strategy_mode", "result_notified", "updated_at",
            }
            missing = required - columns
            if missing:
                raise RuntimeError(
                    "Performance PostgreSQL schema is incomplete; missing columns: "
                    + ", ".join(sorted(missing))
                )
            # Schema changes are applied separately; the app runtime only needs
            # table read/write access, not database-owner DDL privileges.
            con.commit()
            return con
        except Exception:
            con.rollback()
            con.close()
            raise

    # Local development remains compatible with the original SQLite file.
    PERFORMANCE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(PERFORMANCE_DB)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS performance (
        id TEXT PRIMARY KEY, time TEXT, pair TEXT, signal TEXT, entry_price REAL,
        candle_color TEXT, signal_time_utc TEXT, analysis_candle_time_utc TEXT,
        result TEXT NOT NULL, signal_created_utc TEXT, signal_created_bd TEXT,
        outcome_price REAL, outcome_candle_time_utc TEXT, outcome_basis TEXT,
        market_mode TEXT NOT NULL DEFAULT 'real',
        strategy TEXT NOT NULL DEFAULT 'UNKNOWN',
        regime TEXT NOT NULL DEFAULT 'UNKNOWN',
        strategy_mode TEXT NOT NULL DEFAULT 'adaptive',
        result_notified INTEGER NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL
    )""")
    # Safe, idempotent migration for databases created by earlier versions.
    columns = {row[1] for row in con.execute("PRAGMA table_info(performance)").fetchall()}
    if "market_mode" not in columns:
        con.execute("ALTER TABLE performance ADD COLUMN market_mode TEXT NOT NULL DEFAULT 'real'")
    if "result_notified" not in columns:
        con.execute("ALTER TABLE performance ADD COLUMN result_notified INTEGER NOT NULL DEFAULT 0")
    if "strategy" not in columns:
        con.execute("ALTER TABLE performance ADD COLUMN strategy TEXT NOT NULL DEFAULT 'UNKNOWN'")
    if "regime" not in columns:
        con.execute("ALTER TABLE performance ADD COLUMN regime TEXT NOT NULL DEFAULT 'UNKNOWN'")
    if "strategy_mode" not in columns:
        con.execute("ALTER TABLE performance ADD COLUMN strategy_mode TEXT NOT NULL DEFAULT 'adaptive'")
    con.execute("DELETE FROM performance WHERE lower(market_mode) = 'crypto'")
    con.commit()
    return con


def _performance_row(row):
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _telegram_performance_stats(signal_id: str | None = None) -> dict:
    """Read stable signal numbering and cumulative WIN/LOSS totals from the performance DB."""
    con = _performance_db()
    try:
        total = int(con.execute("SELECT COUNT(*) FROM performance").fetchone()[0] or 0)
        wins = int(con.execute("SELECT COUNT(*) FROM performance WHERE result='লাভ'").fetchone()[0] or 0)
        losses = int(con.execute("SELECT COUNT(*) FROM performance WHERE result='লস'").fetchone()[0] or 0)
        number = total
        if signal_id:
            if getattr(con, "backend", "sqlite") == "postgres":
                row = con.execute(
                    """SELECT COUNT(*) FROM performance p
                       WHERE (p.time, p.id) <= (SELECT s.time, s.id FROM performance s WHERE s.id=?)""",
                    (signal_id,),
                ).fetchone()
            else:
                row = con.execute("SELECT COUNT(*) FROM performance WHERE rowid <= (SELECT rowid FROM performance WHERE id=?)", (signal_id,)).fetchone()
            number = int(row[0] or total) if row else total
        return {"signal_number": number, "wins": wins, "losses": losses, "total_signals": total}
    finally:
        con.close()


def _notify_telegram_safely(result: dict) -> None:
    """Telegram failures must not break signal generation or dashboard requests."""
    try:
        payload = dict(result)
        signal = str(payload.get("signal") or "").strip().upper()
        signal_time = payload.get("signal_time_utc") or payload.get("entry_candle_time_utc")
        if signal in {"BUY", "SELL"} and signal_time:
            pair = str(payload.get("pair") or "").strip().upper()
            mode = str(payload.get("market_mode") or "real").strip().lower()
            analysis_time = payload.get("analysis_candle_time_utc")
            signal_id = "|".join([mode, pair, signal, str(signal_time), str(analysis_time or "")])
            payload.update(_telegram_performance_stats(signal_id))
        sent = notify_signal(payload)
        if sent:
            print("[MMC Telegram] New BUY/SELL signal sent.", flush=True)
    except Exception as exc:
        print(f"[MMC Telegram] Signal notification failed: {exc}", flush=True)


def _record_signal_performance(result: dict) -> None:
    """Persist every generated BUY/SELL signal on the server immediately.

    The browser still posts rows for backward compatibility, but signal
    history must not depend on the dashboard tab staying open.
    """
    if not isinstance(result, dict):
        return
    signal = str(result.get("signal") or "").strip().upper()
    if signal not in {"BUY", "SELL"}:
        return
    signal_time = result.get("signal_time_utc") or result.get("entry_candle_time_utc")
    if not signal_time:
        return
    pair = str(result.get("pair") or "").strip().upper()
    analysis_time = result.get("analysis_candle_time_utc")
    mode = str(result.get("market_mode") or "real").strip().lower()
    row = {
        "id": "|".join([mode, pair, signal, str(signal_time), str(analysis_time or "")]),
        "time": result.get("signal_created_bd") or result.get("signal_created_utc") or signal_time,
        "pair": pair,
        "market_mode": mode,
        "strategy": str(result.get("strategy") or "UNKNOWN"),
        "regime": str(result.get("regime") or "UNKNOWN"),
        "strategy_mode": str(result.get("strategy_mode") or "adaptive"),
        "signal": signal,
        "entry_price": result.get("entry_price"),
        "candle_color": result.get("signal_candle_color") or "—",
        "signal_time_utc": signal_time,
        "analysis_candle_time_utc": analysis_time,
        "result": "অপেক্ষমাণ",
        "signal_created_utc": result.get("signal_created_utc"),
        "signal_created_bd": result.get("signal_created_bd"),
        "outcome_price": None,
        "outcome_candle_time_utc": None,
        "outcome_basis": None,
    }
    con = _performance_db()
    try:
        cols = ["id","time","pair","signal","entry_price","candle_color","signal_time_utc","analysis_candle_time_utc","result","signal_created_utc","signal_created_bd","outcome_price","outcome_candle_time_utc","outcome_basis","market_mode","strategy","regime","strategy_mode"]
        vals = [row.get(c) for c in cols]
        con.execute("""INSERT INTO performance
            (id,time,pair,signal,entry_price,candle_color,signal_time_utc,analysis_candle_time_utc,
             result,signal_created_utc,signal_created_bd,outcome_price,outcome_candle_time_utc,outcome_basis,market_mode,strategy,regime,strategy_mode,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
             entry_price=COALESCE(excluded.entry_price,performance.entry_price),
             candle_color=COALESCE(excluded.candle_color,performance.candle_color),
             signal_created_utc=COALESCE(excluded.signal_created_utc,performance.signal_created_utc),
             signal_created_bd=COALESCE(excluded.signal_created_bd,performance.signal_created_bd),
             strategy=CASE WHEN performance.strategy='UNKNOWN' THEN excluded.strategy ELSE performance.strategy END,
             regime=CASE WHEN performance.regime='UNKNOWN' THEN excluded.regime ELSE performance.regime END,
             strategy_mode=excluded.strategy_mode,
             updated_at=excluded.updated_at""", vals + [time.time()])
        con.commit()
    finally:
        con.close()

_DEFAULT_SETTINGS = {
    "market_mode": "",
    "pair": None,
    "auto_signal": False,
    "min_confidence": 0.0,
    "strategy_mode": "normal",
    "timezone": "Asia/Dhaka",
}
_USAGE_CACHE = {"data": None, "at": 0.0}

def _login_configured() -> bool:
    return bool((os.getenv("APP_LOGIN_USERNAME") or "admin").strip() and (os.getenv("APP_LOGIN_PASSWORD") or "").strip())

def _valid_login(username: str, password: str) -> bool:
    expected_user = (os.getenv("APP_LOGIN_USERNAME") or "admin").strip()
    expected_password = os.getenv("APP_LOGIN_PASSWORD") or ""
    return bool(
        expected_password
        and hmac.compare_digest((username or "").strip(), expected_user)
        and hmac.compare_digest(password or "", expected_password)
    )

def _usage_view():
    """Return cached API/credit usage without blocking the dashboard unnecessarily."""
    now = time.time()
    if _USAGE_CACHE["data"] is not None and now - _USAGE_CACHE["at"] < 30:
        return _USAGE_CACHE["data"]
    try:
        api_usage = fetch_api_usage() or {}
    except Exception:
        api_usage = {}
    try:
        credit_usage = get_credit_usage() or {}
    except Exception:
        credit_usage = {}
    data = {"api": api_usage, "credits": credit_usage}
    _USAGE_CACHE["data"] = data
    _USAGE_CACHE["at"] = now
    return data

def _valid_strategy_modes():
    return {"normal", "candle_reaction"}

def _valid_pairs(mode: str):
    return REAL_PAIRS if mode == "real" else QUOTEX_OTC_PAIRS if mode == "quotex_otc" else []

def _settings():
    value = dict(_DEFAULT_SETTINGS)
    value.update(session.get("settings") or {})
    mode = session.get("selected_mode")
    pair = session.get("selected_pair")
    if mode:
        value["market_mode"] = mode
    if pair:
        value["pair"] = pair
    return value

def _save_settings(mode: str, pair: str, auto_signal=None, min_confidence=None, timezone=None, strategy_mode=None):
    current = _settings()
    current["market_mode"] = mode
    current["pair"] = pair
    if auto_signal is not None:
        current["auto_signal"] = bool(auto_signal)
    if min_confidence is not None:
        current["min_confidence"] = float(min_confidence)
    if timezone:
        current["timezone"] = timezone
    if strategy_mode in _valid_strategy_modes():
        current["strategy_mode"] = strategy_mode
    session["settings"] = current
    session["selected_mode"] = mode
    session["selected_pair"] = pair
    return current

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("index"))
    error = None
    if not _login_configured():
        error = "লগইন চালু করতে Render Environment-এ APP_LOGIN_PASSWORD সেট করুন।"
    elif request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if _valid_login(username, password):
            session.clear()
            session["authenticated"] = True
            return redirect(url_for("index"))
        error = "Username অথবা Password ভুল।"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="sk_bot_logo.svg"))

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

def _collector_request_authenticated() -> bool:
    if request.path not in {"/quotex/ingest", "/quotex/real-ingest"}:
        return False
    expected = (os.getenv("QUOTEX_INGEST_SECRET") or "").strip()
    supplied = (request.headers.get("X-MMC-Quotex-Key") or request.args.get("key") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))

@app.before_request
def require_dashboard():
    if _collector_request_authenticated():
        return None
    if request.endpoint in {"login", "logout", "favicon", "privacy", "static"}:
        return None
    if not session.get("authenticated"):
        if request.path.startswith("/api/") or request.path.startswith("/quotex/") or request.path in {"/select-market", "/auto-signal", "/news-alert", "/news-direction"}:
            return jsonify({"ok": False, "error": "লগইন প্রয়োজন।"}), 401
        return redirect(url_for("login"))
    return None

@app.route("/select-market", methods=["POST"])
def select_market():
    mode = request.form.get("mode", "").strip().lower()
    pair = request.form.get("pair", "").strip().upper()
    strategy_mode = request.form.get("strategy_mode", _settings().get("strategy_mode", "normal")).strip().lower()
    if strategy_mode not in _valid_strategy_modes():
        return jsonify({"ok": False, "error": "অবৈধ strategy mode।"}), 400
    if pair not in _valid_pairs(mode):
        return jsonify({"ok": False, "error": "অবৈধ মার্কেট।"}), 400
    _save_settings(mode, pair, strategy_mode=strategy_mode)
    return jsonify({"ok": True, "mode": mode, "pair": pair, "strategy_mode": strategy_mode})

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    saved = _settings()
    if request.method == "POST":
        mode = request.form.get("mode", "").strip().lower()
        pair = request.form.get("pair", "").strip().upper()
        strategy_mode = request.form.get("strategy_mode", "normal").strip().lower()
    else:
        mode = session.get("selected_mode", saved.get("market_mode", ""))
        pair = session.get("selected_pair", saved.get("pair", ""))
        strategy_mode = saved.get("strategy_mode", "normal")
    if mode not in {"real", "quotex_otc"}:
        mode, pair = "", ""
    if strategy_mode not in _valid_strategy_modes():
        strategy_mode = "normal"
    if pair not in _valid_pairs(mode):
        pair = ""
    if request.method == "POST":
        if not pair:
            error = "Please select a market before GET SIGNAL."
        else:
            _save_settings(mode, pair, strategy_mode=strategy_mode)
            try:
                result = get_signal(pair, mode, strategy_mode=strategy_mode)
                _record_signal_performance(result)
                _notify_telegram_safely(result)
            except Exception as exc:
                error = str(exc)
    return render_template(
        "index.html",
        real_pairs=REAL_PAIRS,
        otc_pairs=QUOTEX_OTC_PAIRS,
        mode=mode,
        pair=pair,
        strategy_mode=strategy_mode,
        error=error,
        result=result,
        usage=_usage_view(),
    )

@app.route("/auto-signal", methods=["GET"])
def auto_signal():
    settings = _settings()
    mode = session.get("selected_mode", settings.get("market_mode", "")).strip().lower()
    pair = session.get("selected_pair", settings.get("pair", "") or "").strip().upper()
    strategy_mode = settings.get("strategy_mode", "normal")
    if pair not in _valid_pairs(mode):
        return jsonify({"ok": False, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"}), 400
    try:
        result = get_signal(pair, mode, automatic=True, strategy_mode=strategy_mode)
        _record_signal_performance(result)
        _notify_telegram_safely(result)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

@app.route("/api/telegram-status", methods=["GET"])
def telegram_status():
    return jsonify({
        "ok": True,
        "enabled": telegram_enabled(),
        "configured": bool((os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() and (os.getenv("TELEGRAM_CHAT_ID") or "").strip()),
        "instructions": "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the hosting environment; secrets are never returned.",
    })

@app.route("/api/telegram-chats", methods=["GET"])
def telegram_chats():
    try:
        return jsonify({"ok": True, "chats": get_recent_chats()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

@app.route("/api/telegram-test", methods=["GET", "POST"])
def telegram_test():
    try:
        send_test_message()
        return jsonify({"ok": True, "message": "Telegram test message sent."})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

@app.route("/news-alert", methods=["GET"])
def news_alert():
    mode = session.get("selected_mode", "").strip().lower()
    pair = session.get("selected_pair", "").strip().upper()
    if pair not in _valid_pairs(mode):
        return jsonify({"ok": False, "unselected": True, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"})
    if mode == "quotex_otc":
        return jsonify({"ok": True, "market_mode": mode, "selected_pair": pair, "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "events": [], "alert_events": [], "total_events": 0, "source": "Quotex OTC — economic news filter not used"})
    try:
        return jsonify(get_all_news_events(mode, REAL_PAIRS))
    except Exception:
        try:
            return jsonify(get_weekly_news_events_for_pair(mode, REAL_PAIRS, pair))
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

@app.route("/performance", methods=["GET", "POST", "DELETE"])
def performance():
    con = _performance_db()
    try:
        if request.method == "GET":
            rows = con.execute("SELECT * FROM performance ORDER BY time DESC, updated_at DESC LIMIT 200").fetchall()
            stats_rows = con.execute("""
                SELECT COALESCE(NULLIF(strategy, ''), 'UNKNOWN') AS strategy,
                       COUNT(*) AS total,
                       SUM(CASE WHEN result='লাভ' THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN result='লস' THEN 1 ELSE 0 END) AS losses,
                       SUM(CASE WHEN result='DOJI' THEN 1 ELSE 0 END) AS doji,
                       SUM(CASE WHEN result='অপেক্ষমাণ' THEN 1 ELSE 0 END) AS pending
                FROM performance
                GROUP BY COALESCE(NULLIF(strategy, ''), 'UNKNOWN')
                ORDER BY losses DESC, total DESC
            """).fetchall()
            strategy_stats = []
            for item in stats_rows:
                d = _performance_row(item)
                settled = int(d["wins"] or 0) + int(d["losses"] or 0)
                d["decided"] = settled
                d["loss_rate"] = round((int(d["losses"] or 0) / settled) * 100, 2) if settled else 0.0
                strategy_stats.append(d)
            summary = _performance_row(con.execute("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN result='লাভ' THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN result='লস' THEN 1 ELSE 0 END) AS losses,
                       SUM(CASE WHEN result='DOJI' THEN 1 ELSE 0 END) AS doji,
                       SUM(CASE WHEN result='অপেক্ষমাণ' THEN 1 ELSE 0 END) AS pending
                FROM performance
            """).fetchone())
            summary = {key: int(summary.get(key) or 0) for key in ("total", "wins", "losses", "doji", "pending")}
            summary["decided"] = summary["wins"] + summary["losses"] + summary["doji"]
            return jsonify({"ok": True, "rows": [_performance_row(r) for r in rows], "summary": summary, "strategy_stats": strategy_stats})
        if request.method == "DELETE":
            con.execute("DELETE FROM performance")
            con.commit()
            return jsonify({"ok": True})
        payload = request.get_json(silent=True) or {}
        if not payload.get("id") or str(payload.get("signal", "")).upper() not in {"BUY", "SELL"}:
            return jsonify({"ok": False, "error": "Invalid performance row"}), 400
        cols = ["id","time","pair","signal","entry_price","candle_color","signal_time_utc","analysis_candle_time_utc","result","signal_created_utc","signal_created_bd","outcome_price","outcome_candle_time_utc","outcome_basis","market_mode","strategy","regime","strategy_mode"]
        vals = [payload.get(c) for c in cols]
        vals[14] = payload.get("market_mode") or "real"
        vals[15] = payload.get("strategy") or "UNKNOWN"
        vals[16] = payload.get("regime") or "UNKNOWN"
        vals[17] = payload.get("strategy_mode") or "adaptive"
        con.execute("""INSERT INTO performance
            (id,time,pair,signal,entry_price,candle_color,signal_time_utc,analysis_candle_time_utc,
             result,signal_created_utc,signal_created_bd,outcome_price,outcome_candle_time_utc,outcome_basis,market_mode,strategy,regime,strategy_mode,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
             time=excluded.time,pair=excluded.pair,signal=excluded.signal,entry_price=excluded.entry_price,
             candle_color=excluded.candle_color,signal_time_utc=excluded.signal_time_utc,
             analysis_candle_time_utc=excluded.analysis_candle_time_utc,result=excluded.result,
             signal_created_utc=excluded.signal_created_utc,signal_created_bd=excluded.signal_created_bd,
             outcome_price=excluded.outcome_price,outcome_candle_time_utc=excluded.outcome_candle_time_utc,
             outcome_basis=excluded.outcome_basis,market_mode=COALESCE(excluded.market_mode,performance.market_mode),
             strategy=CASE WHEN performance.strategy='UNKNOWN' THEN excluded.strategy ELSE performance.strategy END,
             regime=CASE WHEN performance.regime='UNKNOWN' THEN excluded.regime ELSE performance.regime END,
             strategy_mode=COALESCE(excluded.strategy_mode,performance.strategy_mode),
             updated_at=excluded.updated_at""",
            vals + [time.time()])
        con.commit()
        return jsonify({"ok": True})
    finally:
        con.close()


def _utc_epoch(value) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _outcome_candles(mode: str, pair: str) -> list[dict]:
    """Fetch the correct market's closed candles for server-side result scoring."""
    if mode == "quotex_otc":
        from data.quotex_otc import fetch_quotex_candles
        from data.otc_markets import asset_for_display
        asset = asset_for_display(pair)
        if not asset:
            return []
        frame = fetch_quotex_candles(asset, interval="1m", count=240)
        return [{"t": row["timestamp"].timestamp(), "o": float(row["open"]), "c": float(row["close"])}
                for _, row in frame.iterrows()]
    if mode == "real":
        # Real Market signals use the authenticated Quotex browser collector cache.
        from quotex_browser_ingest import _REAL_MARKET, _REAL_MARKET_LOCK
        asset = "".join(ch for ch in pair.upper() if ch.isalnum() or ch in "._-")
        with _REAL_MARKET_LOCK:
            state = dict(_REAL_MARKET.get(asset) or {})
            bars = list(state.get("bars") or [])
            updated_at = state.get("updated_at")
        now_epoch = time.time()
        if updated_at is None or now_epoch - float(updated_at) > 60:
            return []
        # Never score a still-forming Real-Market candle. Normalize millisecond
        # timestamps defensively, then require the full 60-second candle to end.
        closed_bars = []
        for row in bars:
            if not all(row.get(k) is not None for k in ("timestamp", "open", "close")):
                continue
            try:
                stamp = float(row["timestamp"])
                if stamp > 10_000_000_000:
                    stamp /= 1000.0
                op, close = float(row["open"]), float(row["close"])
            except (TypeError, ValueError, OverflowError):
                continue
            if stamp + 60 <= now_epoch:
                closed_bars.append({"t": stamp, "o": op, "c": close})
        return closed_bars
    return []


def _score_pending_performance_once() -> None:
    con = _performance_db()
    try:
        rows = [_performance_row(r) for r in con.execute(
            "SELECT * FROM performance WHERE result='অপেক্ষমাণ' OR (result IN ('লাভ','লস','DOJI') AND result_notified=0) ORDER BY updated_at DESC LIMIT 200"
        ).fetchall()]
    finally:
        con.close()
    if not rows:
        return
    now = time.time()
    candle_cache: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        mode = str(row.get("market_mode") or "real").lower()
        pair = str(row.get("pair") or "").strip()
        signal = str(row.get("signal") or "").upper()
        entry_epoch = _utc_epoch(row.get("signal_time_utc"))
        if signal not in {"BUY", "SELL"} or not pair or entry_epoch is None:
            continue
        # The exact entry-minute candle should be scored soon after it closes.
        # Do not repeatedly query for stale legacy pending rows that are older
        # than the available candle window; leave them pending rather than guess.
        if row.get("result") == "অপেক্ষমাণ" and now - entry_epoch > 6 * 3600:
            continue
        key = (mode, pair)
        # Do not request data until the entry candle has completely closed.
        if row.get("result") == "অপেক্ষমাণ" and now < entry_epoch + 60:
            continue
        if key not in candle_cache:
            try:
                candle_cache[key] = _outcome_candles(mode, pair)
            except Exception as exc:
                print(f"[MMC Performance] candle lookup failed mode={mode} pair={pair}: {exc}", flush=True)
                candle_cache[key] = []
        target_minute = int(entry_epoch // 60) * 60
        # Match the exact entry-minute candle and independently verify it has
        # fully closed; missing/stale candle data must remain pending, never guessed.
        candle = next((
            b for b in candle_cache[key]
            if int(float(b["t"]) // 60) * 60 == target_minute
            and float(b["t"]) + 60 <= now
        ), None)
        if not candle:
            continue
        if row.get("result") == "অপেক্ষমাণ":
            op, close = float(candle["o"]), float(candle["c"])
            outcome = "লাভ" if (close > op and signal == "BUY") or (close < op and signal == "SELL") else "লস" if close != op else "DOJI"
            con = _performance_db()
            try:
                con.execute(
                    "UPDATE performance SET result=?, outcome_price=?, outcome_candle_time_utc=?, outcome_basis=?, updated_at=? WHERE id=? AND result='অপেক্ষমাণ'",
                    (outcome, close, datetime.fromtimestamp(target_minute, timezone.utc).isoformat(), "সম্পূর্ণ entry ১-মিনিট candle open-to-close", time.time(), row["id"])
                )
                con.commit()
                row["result"] = outcome
                row["outcome_price"] = close
                row["outcome_candle_time_utc"] = datetime.fromtimestamp(target_minute, timezone.utc).isoformat()
                row["outcome_basis"] = "সম্পূর্ণ entry ১-মিনিট candle open-to-close"
                print(f"[MMC Performance] scored mode={mode} pair={pair} signal={signal} result={outcome}", flush=True)
            finally:
                con.close()
        if row.get("result") in {"লাভ", "লস", "DOJI"} and not int(row.get("result_notified") or 0):
            try:
                row.update(_telegram_performance_stats(row.get("id")))
                sent = notify_signal_result(row)
                if sent:
                    con = _performance_db()
                    try:
                        con.execute("UPDATE performance SET result_notified=1, updated_at=? WHERE id=? AND result_notified=0", (time.time(), row["id"]))
                        con.commit()
                    finally:
                        con.close()
                    print(f"[MMC Telegram] Outcome sent mode={mode} pair={pair} result={row['result']}", flush=True)
            except Exception as exc:
                print(f"[MMC Telegram] Outcome notification failed mode={mode} pair={pair}: {exc}", flush=True)


def _performance_worker() -> None:
    while True:
        try:
            _score_pending_performance_once()
        except Exception as exc:
            print(f"[MMC Performance] background worker error: {exc}", flush=True)
        time.sleep(10)


# Runs independently of the dashboard tab so finalized outcomes can reach Telegram.
threading.Thread(target=_performance_worker, name="mmc-performance-worker", daemon=True).start()


@app.route("/news-direction", methods=["GET"])
def news_direction():
    mode = session.get("selected_mode", "").strip().lower()
    pair = session.get("selected_pair", "").strip().upper()
    if pair not in _valid_pairs(mode):
        return jsonify({"ok": False, "unselected": True, "needed": False, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"})
    if mode == "quotex_otc":
        return jsonify({"ok": True, "needed": False, "pair": pair, "events": [], "source": "Quotex OTC"})
    try:
        return jsonify(get_news_direction_for_pair(mode, pair))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")), debug=False)
