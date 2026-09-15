"""User accounts for the web dashboard.

This module is intentionally separate from the trading engine.  It adds an
account boundary around the existing MMC signal system without changing the
strategy or signal generation code.
"""
from __future__ import annotations

import hmac
import os
from contextlib import contextmanager
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash


def _db_url():
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is not configured for user accounts.")
    return "postgresql://" + value[len("postgres://"):] if value.startswith("postgres://") else value


@contextmanager
def _connect():
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("PostgreSQL driver is not installed.") from exc
    conn = psycopg2.connect(_db_url(), connect_timeout=8)
    try:
        yield conn
    finally:
        conn.close()


def init_users():
    """Create the user table and optionally bootstrap the configured admin."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS mmc_users (
                id BIGSERIAL PRIMARY KEY,
                username VARCHAR(80) NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role VARCHAR(16) NOT NULL DEFAULT 'USER',
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_login_at TIMESTAMPTZ
            )""")
            # Keep the existing APP_USERNAME/APP_PASSWORD deployment compatible.
            username = os.getenv("APP_USERNAME", "admin").strip()
            password = os.getenv("APP_PASSWORD", "")
            if username and password:
                cur.execute("SELECT id FROM mmc_users WHERE username=%s", (username,))
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO mmc_users (username,password_hash,role) VALUES (%s,%s,'MASTER')",
                        (username, generate_password_hash(password)),
                    )
        conn.commit()


def authenticate_user(username: str, password: str) -> Optional[dict]:
    username = (username or "").strip()
    if not username or not password:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,username,password_hash,role,active FROM mmc_users WHERE username=%s", (username,))
            row = cur.fetchone()
            if not row or not row[4] or not check_password_hash(row[2], password):
                return None
            cur.execute("UPDATE mmc_users SET last_login_at=NOW() WHERE id=%s", (row[0],))
        conn.commit()
    return {"id": int(row[0]), "username": row[1], "role": row[3]}


def create_user(username: str, password: str) -> dict:
    username = (username or "").strip()
    if len(username) < 3 or len(username) > 80:
        raise ValueError("Username must be 3-80 characters.")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters.")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM mmc_users WHERE username=%s", (username,))
            if cur.fetchone() is not None:
                raise ValueError("Username already exists.")
            cur.execute(
                "INSERT INTO mmc_users (username,password_hash,role) VALUES (%s,%s,'USER') RETURNING id",
                (username, generate_password_hash(password)),
            )
            user_id = cur.fetchone()[0]
        conn.commit()
    return {"id": int(user_id), "username": username, "role": "USER"}


def get_user(user_id: int) -> Optional[dict]:
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,username,role,active FROM mmc_users WHERE id=%s", (user_id,))
            row = cur.fetchone()
    if not row or not row[3]:
        return None
    return {"id": int(row[0]), "username": row[1], "role": row[2]}
