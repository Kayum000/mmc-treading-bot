"""Application entry point for Render/web deployment.

The deployed service is the on-demand signal UI. It does not place trades.
The old CSV CLI remains available as a separate module if needed.
"""
# Load the conservative signal-density patch before web.app imports
# signals.get_signal, so its imported generate_signal reference is patched.
import strategy.signal_patch

from web.app import app


@app.after_request
def add_auto_signal_guard(response):
    """Make AUTO SIGNAL one-shot so one setup cannot fire repeatedly."""
    if response.content_type and response.content_type.startswith("text/html"):
        html = response.get_data(as_text=True)
        guard = '<script src="/static/auto_signal_guard.js" defer></script>'
        if guard not in html and "</body>" in html:
            html = html.replace("</body>", guard + "</body>")
            response.set_data(html)
    return response


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
