"""Application entry point for Render/web deployment and local MMC server."""
from web.app import app
from flask import request, session
from market_status import init_market_status
from quotex_browser_ingest import init_quotex_browser_ingest
from remember_me import init_remember_me
from master_access import init_master_access
from master_selection_sync import init_master_selection_sync
from master_session_restore import init_master_session_restore
from master_recovery_ui import init_master_recovery_ui
from master_trusted_devices import init_master_trusted_devices

init_market_status(app)
init_remember_me(app)
init_master_access(app)
init_master_selection_sync(app)
init_master_session_restore(app)
init_master_recovery_ui(app)
init_master_trusted_devices(app)
init_quotex_browser_ingest(app)

# The dashboard login middleware in web.app is registered before the collector
# module's hooks. Exempt only this path at the routing layer so the collector
# endpoint itself can perform its own constant-time secret validation and return
# 401/503 instead of being redirected to the HTML login page.
@app.before_request
def allow_quotex_ingest_route():
    if request.path in {"/quotex/ingest", "/quotex/real-ingest"}:
        session["authenticated"] = True
    return None


def _start_embedded_quotex_collector() -> None:
    """Run the Quotex browser collector inside the MMC server process.

    This mode is local-only. The collector attaches to the user's isolated
    Chrome CDP session and posts both Real Market and OTC data back to this
    same Flask process. Render/cloud deployments never start it.
    """
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
    import os
    port = int(os.getenv("PORT", "5000"))
    if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"):
        os.execvp("gunicorn", ["gunicorn", "--bind", f"0.0.0.0:{port}", "--workers", "1", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "main:app"])
    if os.getenv("MMC_LOCAL_SERVER", "0") == "1":
        _start_embedded_quotex_collector()
    app.run(host="0.0.0.0", port=port, debug=False)
