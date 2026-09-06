"""Application entry point for Render/web deployment.

The deployed service is the on-demand signal UI. It does not place trades.
The old CSV CLI remains available as a separate module if needed.
"""
from web.app import app
from web.quotex_integration import install as install_quotex

install_quotex(app)


if __name__ == "__main__":
    import os

    port = int(os.getenv("PORT", "5000"))

    # Render: use a production WSGI server with one worker to avoid duplicating
    # the application's memory footprint. Threads preserve concurrent HTTP
    # handling without starting multiple full Python worker processes.
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

    # Keep the existing local-development behavior unchanged.
    app.run(host="0.0.0.0", port=port, debug=False)
