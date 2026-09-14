"""Application entry point for Render/web deployment."""
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
    if request.path == "/quotex/ingest":
        session["authenticated"] = True
    return None


if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", "5000"))
    if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"):
        import os as _os
        _os.execvp("gunicorn", ["gunicorn", "--bind", f"0.0.0.0:{port}", "--workers", "1", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "main:app"])
    app.run(host="0.0.0.0", port=port, debug=False)