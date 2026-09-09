"""Persistent storage for the shared Master/Viewer state.

Uses the existing Render PostgreSQL database when DATABASE_URL is configured.
The module is intentionally isolated so the trading/signal strategy is not
coupled to the storage implementation.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any

import psycopg2


_TABLE = "mmc_master_state"


class MasterStore:
    def __init__(self) -> None:
        self.database_url = os.getenv("DATABASE_URL", "").strip()
        self.enabled = bool(self.database_url)
        if self.enabled:
            self.initialize()

    @contextmanager
    def _connection(self):
        if not self.enabled:
            raise RuntimeError("DATABASE_URL is not configured.")
        conn = psycopg2.connect(self.database_url, connect_timeout=5)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_TABLE} (
                        id SMALLINT PRIMARY KEY CHECK (id = 1),
                        master_device_hash TEXT,
                        master_device_hash_2 TEXT,
                        mode TEXT NOT NULL DEFAULT '',
                        pair TEXT NOT NULL DEFAULT '',
                        result_json JSONB,
                        updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
                    )
                    """
                )
                cur.execute(f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS master_device_hash_2 TEXT")
                cur.execute(f"""INSERT INTO {_TABLE} (id) VALUES (1) ON CONFLICT (id) DO NOTHING""")

    def get_state(self) -> dict[str, Any]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT master_device_hash, master_device_hash_2, mode, pair, result_json, updated_at FROM {_TABLE} WHERE id = 1"
                )
                row = cur.fetchone()
        if not row:
            return {"master_device_hash": None, "master_device_hash_2": None, "mode": "", "pair": "", "result": None, "updated_at": 0.0}
        return {
            "master_device_hash": row[0],
            "master_device_hash_2": row[1],
            "mode": row[2] or "",
            "pair": row[3] or "",
            "result": row[4],
            "updated_at": float(row[5] or 0.0),
        }

    def claim_master(self, device_hash: str) -> tuple[bool, str]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT master_device_hash, master_device_hash_2 FROM {_TABLE} WHERE id = 1 FOR UPDATE")
                row = cur.fetchone()
                first = row[0] if row else None
                second = row[1] if row else None
                if device_hash == first or device_hash == second:
                    return True, "MASTER device is already authorized."
                if not first:
                    cur.execute(f"UPDATE {_TABLE} SET master_device_hash = %s WHERE id = 1", (device_hash,))
                    return True, "MASTER device 1 authorized successfully."
                if not second:
                    cur.execute(f"UPDATE {_TABLE} SET master_device_hash_2 = %s WHERE id = 1", (device_hash,))
                    return True, "MASTER device 2 authorized successfully."
                return False, "Both MASTER device slots are already in use."

    def recover_master(self, device_hash: str, slot: int) -> tuple[bool, str]:
        """Explicitly replace one Master slot; caller must validate the setup key."""
        if slot not in (1, 2):
            return False, "Invalid MASTER slot."
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT master_device_hash, master_device_hash_2 FROM {_TABLE} WHERE id = 1 FOR UPDATE")
                row = cur.fetchone()
                first = row[0] if row else None
                second = row[1] if row else None
                if device_hash == first or device_hash == second:
                    return True, "MASTER device is already authorized."
                column = "master_device_hash" if slot == 1 else "master_device_hash_2"
                cur.execute(f"UPDATE {_TABLE} SET {column} = %s WHERE id = 1", (device_hash,))
                return True, f"MASTER device {slot} was restored successfully."

    def is_master_hash(self, device_hash: str) -> bool:
        state = self.get_state()
        return device_hash in {state.get("master_device_hash"), state.get("master_device_hash_2")}

    def update_selection(self, mode: str, pair: str, updated_at: float) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""UPDATE {_TABLE} SET mode = %s, pair = %s, result_json = NULL, updated_at = %s WHERE id = 1""",
                    (mode, pair, updated_at),
                )

    def update_signal(self, mode: str, pair: str, result: Any, updated_at: float) -> None:
        payload = json.dumps(result, default=str)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""UPDATE {_TABLE} SET mode = %s, pair = %s, result_json = %s::jsonb, updated_at = %s WHERE id = 1""",
                    (mode, pair, payload, updated_at),
                )


store = MasterStore()
