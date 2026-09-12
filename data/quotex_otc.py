"""Quotex OTC 1-minute candle data adapter (data only; no trade execution)."""
from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import os
import time
from pathlib import Path

import pandas as pd

OTC_PAIRS = (
    "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "AUDUSD_otc", "USDCAD_otc",
    "USDCHF_otc", "NZDUSD_otc", "EURJPY_otc", "GBPJPY_otc", "XAUUSD_otc",
)
_PERIOD = 60
_FETCH_TIMEOUT = 90
_CACHE_TTL = 15
_LOCK = mp.RLock()
_CACHE: dict[tuple[str, int], tuple[float, pd.DataFrame]] = {}
_BLOCK_UNTIL = 0.0
_BLOCK_ERROR = ""
_LOG = logging.getLogger(__name__)


def _rss_mb() -> float:
    try:
        for line in Path("/proc/self/status").read_text(errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


async def _fetch_once(asset: str, count: int):
    """Login/reuse SSID, fetch candles over WebSocket, then close cleanly."""
    email = os.getenv("QUOTEX_EMAIL", "").strip()
    password = os.getenv("QUOTEX_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("Quotex OTC চালাতে QUOTEX_EMAIL/QUOTEX_PASSWORD সেট করতে হবে।")

    try:
        from api_quotex import AsyncQuotexClient, get_ssid
    except Exception as exc:
        raise RuntimeError(f"API-Quotex load failed: {type(exc).__name__}: {exc}") from exc

    # Preserve the previous QuotexPy default account behavior: DEMO/OTC data.
    # The API-Quotex login helper first validates its saved SSID, then uses a
    # lightweight Cloudscraper login and only falls back to Playwright when
    # needed. This removes the unstable undetected-chromedriver path entirely.
    is_demo = os.getenv("QUOTEX_DEMO", "1").strip().lower() not in {"0", "false", "no"}
    ok, session = await asyncio.wait_for(
        get_ssid(
            email=email,
            password=password,
            lang=os.getenv("QUOTEX_LANG", "en"),
            is_demo=is_demo,
        ),
        timeout=70,
    )
    if not ok or not isinstance(session, dict):
        raise RuntimeError("Quotex login/SSID retrieval failed.")
    ssid = str(session.get("ssid") or "").strip()
    if not ssid:
        raise RuntimeError("Quotex login succeeded but no SSID was returned.")

    client = AsyncQuotexClient(
        ssid=ssid,
        is_demo=is_demo,
        persistent_connection=False,
        auto_reconnect=False,
        enable_logging=False,
    )
    try:
        connected = await asyncio.wait_for(client.connect(), timeout=25)
        if not connected:
            raise RuntimeError("Quotex WebSocket connection failed.")
        df = await asyncio.wait_for(
            client.get_candles_dataframe(asset, _PERIOD, count=int(count)),
            timeout=25,
        )
        if df is None or df.empty:
            raise RuntimeError(f"Quotex returned no candle data for {asset}.")
        return df.reset_index().to_dict(orient="records")
    finally:
        try:
            await asyncio.wait_for(client.disconnect(), timeout=5)
        except Exception:
            pass


def _child_fetch(asset: str, count: int, conn) -> None:
    """Run the whole browser/WS stack outside the Gunicorn worker."""
    try:
        payload = asyncio.run(_fetch_once(asset, count))
        conn.send((True, payload))
    except BaseException as exc:
        try:
            conn.send((False, f"{type(exc).__name__}: {exc}"))
        except BaseException:
            pass
    finally:
        try:
            conn.close()
        except BaseException:
            pass


def _isolated_fetch(asset: str, count: int):
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_child_fetch,
        args=(asset, count, child_conn),
        name="quotex-fetch",
    )
    process.daemon = False
    process.start()
    child_conn.close()
    try:
        deadline = time.monotonic() + _FETCH_TIMEOUT
        while time.monotonic() < deadline:
            if parent_conn.poll(0.25):
                try:
                    ok, value = parent_conn.recv()
                except EOFError as exc:
                    process.join(timeout=0.5)
                    raise RuntimeError(
                        f"Quotex child exited before returning data (exit={process.exitcode})."
                    ) from exc
                if not ok:
                    process.join(timeout=0.5)
                    raise RuntimeError(f"Quotex fetch failed: {value}")
                return value
            if not process.is_alive():
                process.join(timeout=0.5)
                raise RuntimeError(f"Quotex child exited without data (exit={process.exitcode}).")
        raise RuntimeError("Quotex request timed out; isolated process was terminated safely.")
    finally:
        parent_conn.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=3)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)


def _rows(payload):
    if isinstance(payload, dict):
        payload = payload.get("data", payload.get("candles", payload.get("values", [])))
    if isinstance(payload, dict):
        payload = list(payload.values())
    if not isinstance(payload, list):
        return []
    out = []
    for item in payload:
        if isinstance(item, dict):
            ts = item.get("timestamp", item.get("time", item.get("from")))
            op = item.get("open")
            hi = item.get("high")
            lo = item.get("low")
            cl = item.get("close")
        elif isinstance(item, (list, tuple)) and len(item) >= 5:
            ts, op, cl, hi, lo = item[:5]
        else:
            continue
        try:
            if isinstance(ts, pd.Timestamp):
                stamp = ts
            else:
                stamp = pd.Timestamp(ts)
                if stamp.tzinfo is None:
                    stamp = stamp.tz_localize("UTC")
                else:
                    stamp = stamp.tz_convert("UTC")
            out.append({
                "timestamp": stamp,
                "open": float(op), "high": float(hi), "low": float(lo), "close": float(cl),
            })
        except (TypeError, ValueError, OSError):
            continue
    return out


def fetch_quotex_candles(asset: str, interval: str = "1m", count: int = 240) -> pd.DataFrame:
    global _BLOCK_UNTIL, _BLOCK_ERROR
    asset = str(asset).strip()
    canonical = next((p for p in OTC_PAIRS if p.lower() == asset.lower()), None)
    if not canonical:
        raise ValueError("Unsupported Quotex OTC market")
    if interval != "1m":
        raise ValueError("Quotex OTC MMC uses 1-minute candles only")

    key = (canonical, int(count))
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1].copy(deep=True)
    if now < _BLOCK_UNTIL:
        raise RuntimeError(_BLOCK_ERROR or "Quotex access is temporarily blocked; retry later.")

    with _LOCK:
        now = time.monotonic()
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1].copy(deep=True)
        max_rss = float(os.getenv("QUOTEX_MAX_RSS_MB", "430"))
        if _rss_mb() >= max_rss:
            raise RuntimeError("Quotex OTC temporarily paused by memory guard.")
        try:
            payload = _isolated_fetch(canonical, int(count))
            rows = _rows(payload)
            if not rows:
                raise RuntimeError(f"Quotex returned no candle data for {canonical}.")
            df = pd.DataFrame(rows).drop_duplicates("timestamp").sort_values("timestamp")
            boundary = pd.Timestamp((int(time.time()) // _PERIOD) * _PERIOD, unit="s", tz="UTC")
            df = df.loc[df["timestamp"] < boundary].tail(int(count)).reset_index(drop=True)
            if len(df) < 60:
                raise RuntimeError(f"Quotex returned only {len(df)} closed 1m candles for {canonical}.")
            _BLOCK_UNTIL = 0.0
            _BLOCK_ERROR = ""
            _CACHE[key] = (time.monotonic(), df)
            return df.copy(deep=True)
        except Exception as exc:
            _LOG.exception("Quotex OTC fetch failed for %s: %s", canonical, exc)
            text = str(exc).lower()
            if "403" in text or "forbidden" in text or "cloudflare" in text:
                _BLOCK_ERROR = "Quotex returned an access/Cloudflare block from the server."
                _BLOCK_UNTIL = time.monotonic() + 90
            raise


def quotex_status(asset: str) -> dict:
    started = time.time()
    try:
        df = fetch_quotex_candles(asset, "1m", 80)
        return {
            "ok": True, "connected": True, "asset": asset, "timeframe": "1m",
            "closed_candles": len(df),
            "latest_closed_candle": pd.Timestamp(df.iloc[-1]["timestamp"]).strftime("%d %b %Y, %H:%M:%S UTC"),
            "source": "Quotex OTC", "latency_ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        return {
            "ok": False, "connected": False, "asset": asset, "timeframe": "1m",
            "error": str(exc), "source": "Quotex OTC", "latency_ms": int((time.time() - started) * 1000),
        }
