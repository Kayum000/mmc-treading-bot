"""Application entry point for Render/web deployment and local MMC server."""
from web.app import app
from flask import request, session
from market_status import init_market_status
from quotex_browser_ingest import init_quotex_browser_ingest

from web.admin import init_admin_routes
init_admin_routes(app)

from web.admin_app import init_admin_app_routes
init_admin_app_routes(app)

from web.user_profile import init_user_profile_routes
init_user_profile_routes(app)

import web.app as web_app


def _collector_request_authenticated_for_embedded() -> bool:
    if request.path not in {"/quotex/ingest", "/quotex/real-ingest"}:
        return False
    expected = (os.getenv("QUOTEX_INGEST_SECRET") or "").strip()
    supplied = (request.headers.get("X-MMC-Quotex-Key") or request.args.get("key") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))


import hmac
import os
web_app._collector_request_authenticated = _collector_request_authenticated_for_embedded

init_market_status(app)
init_quotex_browser_ingest(app)


@app.before_request
def allow_quotex_ingest_route():
    if request.path in {"/quotex/ingest", "/quotex/real-ingest"}:
        session["authenticated"] = True
    return None


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
    app.run(host="0.0.0.0", port=port, debug=False)
