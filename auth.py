"""Database-backed multi-user authentication for the MMC dashboard."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Optional

import psycopg2


def _db_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is not configured.")
    return "postgresql://" + value[len("postgres://"):] if value.startswith("postgres://") else value


def _connect():
    return psycopg2.connect(_db_url(), connect_timeout=8)


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        kind, salt_hex, digest_hex = encoded.split("$", 2)
        if kind != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual.hex(), digest_hex)
    except Exception:
        return False


def init_user_db() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS mmc_users (
                id BIGSERIAL PRIMARY KEY, username VARCHAR(64) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE, password_hash TEXT NOT NULL,
                role VARCHAR(16) NOT NULL DEFAULT 'user', active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_login_at TIMESTAMPTZ
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS mmc_user_settings (
                user_id BIGINT PRIMARY KEY REFERENCES mmc_users(id) ON DELETE CASCADE,
                market_mode VARCHAR(16) NOT NULL DEFAULT 'real', pair VARCHAR(32),
                auto_signal BOOLEAN NOT NULL DEFAULT FALSE, min_confidence DOUBLE PRECISION DEFAULT 0.0,
                timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Dhaka', updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS mmc_user_permissions (
                user_id BIGINT PRIMARY KEY REFERENCES mmc_users(id) ON DELETE CASCADE,
                signal_access BOOLEAN NOT NULL DEFAULT TRUE,
                auto_signal_access BOOLEAN NOT NULL DEFAULT TRUE,
                real_market_access BOOLEAN NOT NULL DEFAULT TRUE,
                demo_market_access BOOLEAN NOT NULL DEFAULT TRUE,
                advanced_settings_access BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS mmc_admin_audit (
                id BIGSERIAL PRIMARY KEY,
                actor_user_id BIGINT REFERENCES mmc_users(id) ON DELETE SET NULL,
                action VARCHAR(64) NOT NULL,
                target_user_id BIGINT REFERENCES mmc_users(id) ON DELETE SET NULL,
                details TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS mmc_system_settings (
                key VARCHAR(64) PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
        conn.commit()


def create_user(username: str, password: str, email: str = "", active: bool = False) -> int:
    username = username.strip().lower()
    email = email.strip().lower() or None
    if len(username) < 3 or len(username) > 64:
        raise ValueError("Username must be 3-64 characters.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    init_user_db()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO mmc_users (username,email,password_hash,active) VALUES (%s,%s,%s,%s) RETURNING id", (username, email, _hash_password(password), bool(active)))
            user_id = int(cur.fetchone()[0])
            cur.execute("INSERT INTO mmc_user_settings (user_id) VALUES (%s)", (user_id,))
            cur.execute("INSERT INTO mmc_user_permissions (user_id) VALUES (%s)", (user_id,))
        conn.commit()
    return user_id


def authenticate(username: str, password: str) -> Optional[dict]:
    username = username.strip().lower()
    init_user_db()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,username,email,role,active,password_hash FROM mmc_users WHERE username=%s", (username,))
            row = cur.fetchone()
            if not row or not row[4] or not _verify_password(password, row[5]):
                return None
            cur.execute("UPDATE mmc_users SET last_login_at=NOW() WHERE id=%s", (row[0],))
        conn.commit()
    return {"id": int(row[0]), "username": row[1], "email": row[2] or "", "role": row[3]}


def ensure_env_admin() -> None:
    username = os.getenv("APP_USERNAME", "admin").strip().lower()
    password = os.getenv("APP_PASSWORD", "")
    if not password:
        return
    init_user_db()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM mmc_users WHERE username=%s", (username,))
            row = cur.fetchone()
            if row is None:
                cur.execute("INSERT INTO mmc_users (username,password_hash,role,active) VALUES (%s,%s,'owner',TRUE) RETURNING id", (username, _hash_password(password)))
                owner_id = int(cur.fetchone()[0])
                cur.execute("INSERT INTO mmc_user_settings (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (owner_id,))
                cur.execute("INSERT INTO mmc_user_permissions (user_id,advanced_settings_access) VALUES (%s,TRUE) ON CONFLICT DO NOTHING", (owner_id,))
            else:
                cur.execute("UPDATE mmc_users SET role='owner',active=TRUE WHERE id=%s", (row[0],))
                cur.execute("INSERT INTO mmc_user_permissions (user_id,advanced_settings_access) VALUES (%s,TRUE) ON CONFLICT DO NOTHING", (row[0],))
        conn.commit()


def get_user(user_id: int) -> Optional[dict]:
    init_user_db()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,username,email,role,active FROM mmc_users WHERE id=%s", (int(user_id),))
            row = cur.fetchone()
    if not row or not row[4]:
        return None
    return {"id": int(row[0]), "username": row[1], "email": row[2] or "", "role": row[3]}


def get_settings(user_id: int) -> dict:
    init_user_db()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT market_mode,pair,auto_signal,min_confidence,timezone FROM mmc_user_settings WHERE user_id=%s", (int(user_id),))
            row = cur.fetchone()
    if not row:
        return {"market_mode": "real", "pair": None, "auto_signal": False, "min_confidence": 0.0, "timezone": "Asia/Dhaka"}
    return {"market_mode": row[0], "pair": row[1], "auto_signal": bool(row[2]), "min_confidence": float(row[3] or 0), "timezone": row[4]}


def save_settings(user_id: int, market_mode: str, pair: str, auto_signal: bool, min_confidence: float, timezone: str) -> None:
    init_user_db()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO mmc_user_settings (user_id,market_mode,pair,auto_signal,min_confidence,timezone)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (user_id) DO UPDATE SET market_mode=EXCLUDED.market_mode,pair=EXCLUDED.pair,
                auto_signal=EXCLUDED.auto_signal,min_confidence=EXCLUDED.min_confidence,timezone=EXCLUDED.timezone,updated_at=NOW()""",
                (int(user_id), market_mode, pair or None, bool(auto_signal), float(min_confidence), timezone or "Asia/Dhaka"))
        conn.commit()
