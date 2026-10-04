"""Application entry point for Render/web deployment and local MMC server."""
import os

if os.getenv("MMC_LOCAL_SERVER", "0") == "1":
    from pathlib import Path
    from dotenv import load_dotenv

    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env", override=False)
    secret_file = root / "tools" / ".quotex_test_secret"
    try:
        local_secret = secret_file.read_text(encoding="utf-8").strip()
        if local_secret:
            # The local secret file is the source of truth for the embedded
            # collector. This prevents a stale parent-process environment
            # variable from overriding the Render-synchronized secret.
            os.environ["QUOTEX_INGEST_SECRET"] = local_secret
    except OSError:
        pass

from web.app import app
from market_status import init_market_status
from quotex_browser_ingest import init_quotex_browser_ingest

init_market_status(app)
init_quotex_browser_ingest(app)


def _start_embedded_quotex_collector() -> None:
    """Run the Quotex browser collector inside the MMC server process."""
    import asyncio
    import threading
    import time
    from tools.quotex_local_collector import run as collector_run

    def worker() -> None:
        while True:
            try:
                asyncio.run(collector_run())
            except Exception as exc:
                print(f"[MMC Embedded Quotex] collector stopped: {exc}", flush=True)
            time.sleep(3)

    threading.Thread(target=worker, name="mmc-quotex-collector", daemon=True).start()
    print("[MMC] Embedded Quotex Real Market + OTC collector started in server process.", flush=True)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"):
        os.execvp("gunicorn", ["gunicorn", "--bind", f"0.0.0.0:{port}", "--workers", "1", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "main:app"])
    if os.getenv("MMC_LOCAL_SERVER", "0") == "1":
        _start_embedded_quotex_collector()
    host = "127.0.0.1" if os.getenv("MMC_LOCAL_SERVER", "0") == "1" else "0.0.0.0"
    app.run(host=host, port=port, debug=False)
