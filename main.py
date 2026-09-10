"""Application entry point for Render/web deployment.

The deployed service is the on-demand signal UI. It does not place trades.
The old CSV CLI remains available as a separate module if needed.
"""
from web.app import app
from remember_me import init_remember_me
from master_access import init_master_access
from master_selection_sync import init_master_selection_sync

# Attach the isolated login persistence layer before the existing Master/Viewer
# layers. This leaves the active authentication and signal strategy intact.
init_remember_me(app)
init_master_access(app)
init_master_selection_sync(app)


if __name__ == "__main__":
    import os

    port = int(os.getenv("PORT", "5000"))

    if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"):
        os.execvp(
            "gunicorn",
            [
                "gunicorn",
                "--bind", f"0.0.0.0:{port}",
                "--workers", "1",
                "--threads", "4",
                "--timeout", "120",
                "--access-logfile", "-",
                "--error-logfile", "-",
                "main:app",
            ],
        )

    app.run(host="0.0.0.0", port=port, debug=False)
