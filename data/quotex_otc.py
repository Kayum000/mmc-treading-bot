"""Quotex OTC 1-minute candle data adapter.

Data-only integration: this module never places trades. Credentials are read
from environment variables and the returned frame contains closed OHLC candles.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path
import threading

import pandas as pd

OTC_PAIRS = [
    "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "AUDUSD_otc", "USDCAD_otc",
    "USDCHF_otc", "NZDUSD_otc", "EURJPY_otc", "GBPJPY_otc", "XAUUSD_otc",
]
_PERIOD = 60
# Quotex/Chromium is expensive on the 512 MB Render instance. Never allow two
# OTC browser sessions to start at the same time, and reuse a very recent candle
# snapshot for dashboard polling. Signal logic still receives the same 1m data.
_QUOTEX_LOCK = threading.Lock()
_CANDLE_CACHE = {}
_CANDLE_CACHE_TTL = 15.0
_STATUS_CACHE = {}
_STATUS_CACHE_TTL = 15.0
_BROWSER_USER_DATA = None


def _memory_rss_mb() -> float:
    """Return this process RSS in MB without importing another dependency."""
    try:
        status = Path("/proc/self/status").read_text(errors="ignore")
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def _cleanup_browser_processes() -> None:
    """Best-effort cleanup of Chromium/driver processes left by quotexpy.

    quotexpy's ``close()`` does not always reap Selenium/Chromium children.
    On the single-worker Render service, explicitly reaping only processes
    launched by this adapter prevents browser RSS from accumulating between
    OTC requests.
    """
    global _BROWSER_USER_DATA

    # Prefer psutil when it is already installed; otherwise use the narrow
    # process-name fallback. Never kill the Gunicorn/Python process itself.
    try:
        import psutil
        current_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
            try:
                pid = proc.info["pid"]
                if pid == current_pid:
                    continue
                name = (proc.info.get("name") or "").lower()
                cmd = " ".join(proc.info.get("cmdline") or []).lower()
                marked = "mmc-chrome-" in cmd
                browser = any(x in name for x in ("chromium", "chrome", "chromedriver"))
                if marked or (browser and ("--headless" in cmd or "chromedriver" in name)):
                    proc.terminate()
                    try:
                        proc.wait(timeout=1.5)
                    except Exception:
                        proc.kill()
            except Exception:
                continue
    except Exception:
        # Keep this fallback deliberately narrow: only our per-process user
        # data directory is targeted, so unrelated browser sessions are not hit.
        try:
            subprocess.run(
                ["pkill", "-TERM", "-f", f"--user-data-dir=/tmp/mmc-chrome-{os.getpid()}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
        except Exception:
            pass

    if _BROWSER_USER_DATA:
        try:
            shutil.rmtree(_BROWSER_USER_DATA, ignore_errors=True)
        except Exception:
            pass
        _BROWSER_USER_DATA = None


def _run(value, timeout: float | None = None):
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        async def _wait():
            if timeout is None:
                return await value
            return await asyncio.wait_for(value, timeout=timeout)
        return asyncio.run(_wait())
    return value


def _install_selenium_browser_fallback():
    """Launch a Render-safe Chromium/driver instead of UC auto-downloading one."""
    import undetected_chromedriver as uc
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    if getattr(uc, "_mmc_selenium_fallback", False):
        return

    original = uc.Chrome

    def _chrome_fallback(*args, **kwargs):
        global _BROWSER_USER_DATA
        options = kwargs.pop("options", None)
        kwargs.pop("use_subprocess", None)
        kwargs.pop("driver_executable_path", None)
        kwargs.pop("version_main", None)
        kwargs.pop("patcher_force_close", None)
        kwargs.pop("suppress_welcome", None)
        kwargs.pop("no_sandbox", None)
        kwargs.pop("user_multi_procs", None)
        kwargs.pop("headless", None)
        browser_executable_path = kwargs.pop("browser_executable_path", None)

        if args:
            return original(*args, options=options, **kwargs)

        if options is None:
            options = uc.ChromeOptions()

        browser_path = browser_executable_path or os.getenv("CHROME_BIN", "")
        if not browser_path:
            for candidate in (
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
            ):
                if Path(candidate).exists():
                    browser_path = candidate
                    break
        if browser_path:
            options.binary_location = browser_path

        # quotexpy may explicitly pass headless=False. Render has no X server,
        # so force headless mode regardless of the upstream value.
        flags = (
            "--headless",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-breakpad",
            "--disable-crash-reporter",
            "--disable-features=UseDBus,Translate,MediaRouter",
            "--disable-ipc-flooding-protection",
            "--disable-notifications",
            "--disable-popup-blocking",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-pipe",
            "--window-size=1280,720",
        )
        for flag in flags:
            options.add_argument(flag)

        user_data = f"/tmp/mmc-chrome-{os.getpid()}"
        _BROWSER_USER_DATA = user_data
        Path(user_data).mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={user_data}")

        driver_path = os.getenv("CHROMEDRIVER_BIN", "")
        service = None
        if driver_path and Path(driver_path).exists():
            service = Service(
                executable_path=driver_path,
                log_output="/tmp/mmc-chromedriver.log",
            )
        try:
            return webdriver.Chrome(service=service, options=options)
        except Exception as exc:
            log_path = Path("/tmp/mmc-chromedriver.log")
            detail = ""
            if log_path.exists():
                try:
                    detail = log_path.read_text(errors="replace")[-5000:]
                except Exception:
                    pass
            _cleanup_browser_processes()
            if detail:
                raise RuntimeError(f"ChromeDriver launch failed: {exc}\n{detail}") from exc
            raise

    uc.Chrome = _chrome_fallback
    uc._mmc_selenium_fallback = True


def _client():
    try:
        from quotexpy import Quotex
    except Exception as exc:
        raise RuntimeError(
            f"Quotex data library load failed: {type(exc).__name__}: {exc}"
        ) from exc

    email = os.getenv("QUOTEX_EMAIL", "").strip()
    password = os.getenv("QUOTEX_PASSWORD", "")
    ssid = os.getenv("QUOTEX_SSID", "").strip()
    if not ssid and (not email or not password):
        raise RuntimeError("Quotex OTC চালাতে QUOTEX_EMAIL/QUOTEX_PASSWORD বা QUOTEX_SSID সেট করুন।")

    if not ssid:
        try:
            _install_selenium_browser_fallback()
        except Exception as exc:
            raise RuntimeError(
                f"Quotex browser fallback load failed: {type(exc).__name__}: {exc}"
            ) from exc

    kwargs = {"lang": os.getenv("QUOTEX_LANG", "en")}
    if ssid:
        kwargs["ssid"] = ssid
    return Quotex(email=email, password=password, **kwargs)


def _normalise_rows(payload):
    if isinstance(payload, dict):
        payload = payload.get("data", payload.get("candles", payload.get("values", [])))
    if isinstance(payload, dict):
        payload = list(payload.values())
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload:
        if isinstance(item, dict):
            ts = item.get("time", item.get("timestamp", item.get("from")))
            op, hi, lo, cl = item.get("open"), item.get("high"), item.get("low"), item.get("close")
        elif isinstance(item, (list, tuple)) and len(item) >= 5:
            ts, op, cl, hi, lo = item[:5]
        else:
            continue
        try:
            ts_num = float(ts)
            if ts_num > 10_000_000_000:
                ts_num /= 1000.0
            rows.append({
                "timestamp": pd.Timestamp.fromtimestamp(ts_num, tz="UTC"),
                "open": float(op), "high": float(hi), "low": float(lo), "close": float(cl),
            })
        except (TypeError, ValueError, OSError):
            continue
    return rows


def _fetch_sync(asset: str, count: int = 200):
    canonical = next((item for item in OTC_PAIRS if item.lower() == str(asset).strip().lower()), "")
    if not canonical:
        raise ValueError("Unsupported Quotex OTC market")
    cache_key = (canonical, int(count))
    now = time.monotonic()
    cached = _CANDLE_CACHE.get(cache_key)
    if cached and now - cached[0] < _CANDLE_CACHE_TTL:
        return cached[1].copy(deep=True)

    with _QUOTEX_LOCK:
        now = time.monotonic()
        cached = _CANDLE_CACHE.get(cache_key)
        if cached and now - cached[0] < _CANDLE_CACHE_TTL:
            return cached[1].copy(deep=True)

        # Do not start another Chromium instance when the service is already
        # close to the 512 MB Render limit. This prevents an OTC request from
        # turning a temporary spike into a full service restart.
        rss = _memory_rss_mb()
        max_rss = float(os.getenv("QUOTEX_MAX_RSS_MB", "400"))
        if rss >= max_rss:
            raise RuntimeError(
                f"Quotex browser temporarily paused: service memory is {rss:.0f} MB (limit guard {max_rss:.0f} MB)."
            )

        client = None
        try:
            client = _client()
            check = _run(client.connect(), timeout=35)
            ok = check[0] if isinstance(check, tuple) else bool(check)
            if not ok:
                reason = check[1] if isinstance(check, tuple) and len(check) > 1 else "unknown connection error"
                raise RuntimeError(f"Quotex connection failed: {reason}")

            offset = _PERIOD * max(count + 20, 220)
            payload = _run(client.get_candles(canonical, offset, _PERIOD), timeout=25)
            rows = _normalise_rows(payload)
            if not rows:
                raise RuntimeError(f"Quotex returned no candle data for {canonical}.")

            df = pd.DataFrame(rows).drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
            boundary = pd.Timestamp((int(time.time()) // _PERIOD) * _PERIOD, unit="s", tz="UTC")
            df = df.loc[df["timestamp"] < boundary].tail(count).reset_index(drop=True)
            if len(df) < 27:
                raise RuntimeError(f"Quotex returned only {len(df)} closed 1m candles for {canonical}; at least 27 are required.")
            _CANDLE_CACHE[cache_key] = (time.monotonic(), df)
            return df.copy(deep=True)
        except Exception as exc:
            # A stale browser/login script can fail before close(); always reap
            # the browser so the next request starts from a clean state.
            if "javascript" in str(exc).lower() or "selenium" in type(exc).__module__.lower():
                raise RuntimeError(f"Quotex browser/login compatibility error: {exc}") from exc
            raise
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            _cleanup_browser_processes()


def fetch_quotex_candles(asset: str, interval: str = "1m", count: int = 200) -> pd.DataFrame:
    asset = str(asset).strip()
    canonical = next((item for item in OTC_PAIRS if item.lower() == asset.lower()), "")
    if not canonical:
        raise ValueError("Unsupported Quotex OTC market")
    if interval != "1m":
        raise ValueError("Only the 1m timeframe is supported for Quotex OTC MMC")
    return _fetch_sync(canonical, count=count)


def quotex_status(asset: str) -> dict:
    canonical = next((item for item in OTC_PAIRS if item.lower() == str(asset).strip().lower()), "")
    if not canonical:
        return {"ok": False, "connected": False, "asset": asset, "timeframe": "1m", "error": "Unsupported Quotex OTC market", "source": "Quotex OTC", "latency_ms": 0}

    cache_key = canonical
    now = time.monotonic()
    cached = _STATUS_CACHE.get(cache_key)
    if cached and now - cached[0] < _STATUS_CACHE_TTL:
        return dict(cached[1])

    started = time.time()
    try:
        df = fetch_quotex_candles(canonical, "1m", 40)
        result = {"ok": True, "connected": True, "asset": canonical, "timeframe": "1m", "closed_candles": len(df), "latest_closed_candle": pd.Timestamp(df.iloc[-1]["timestamp"]).strftime("%d %b %Y, %H:%M:%S UTC"), "source": "Quotex OTC", "latency_ms": int((time.time() - started) * 1000)}
    except Exception as exc:
        result = {"ok": False, "connected": False, "asset": canonical, "timeframe": "1m", "error": str(exc), "source": "Quotex OTC", "latency_ms": int((time.time() - started) * 1000)}
    _STATUS_CACHE[cache_key] = (time.monotonic(), result)
    return dict(result)
