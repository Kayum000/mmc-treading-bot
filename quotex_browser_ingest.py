"""Authenticated ingest endpoint for the local Quotex browser collector.

The endpoint accepts candle data only. It never accepts or stores a Quotex
SSID/session token and it never places orders.
"""
from __future__ import annotations

import hmac
import os
import time
from flask import jsonify, request

from data.quotex_otc import ingest_local_candles, local_stream_status


def init_quotex_browser_ingest(app):
    # The main web app has a global login guard registered before this module is
    # initialized. The collector is a machine-to-machine endpoint, so it must
    # reach its own secret check without a browser login/session cookie.
    def allow_collector_endpoint():
        if request.endpoint == "quotex_ingest":
            return None
        return None

    app.before_request_funcs.setdefault(None, []).insert(0, allow_collector_endpoint)

    @app.route("/quotex/ingest", methods=["POST"])
    def quotex_ingest():
        expected = (os.getenv("QUOTEX_INGEST_SECRET") or "").strip()
        supplied = (request.headers.get("X-MMC-Quotex-Key") or request.args.get("key") or "").strip()
        if not expected:
            return jsonify({"ok": False, "error": "QUOTEX_INGEST_SECRET is not configured on the server."}), 503
        if not supplied or not hmac.compare_digest(supplied, expected):
            return jsonify({"ok": False, "error": "Invalid ingest key."}), 401
        if not request.is_json:
            return jsonify({"ok": False, "error": "JSON body required."}), 415
        payload = request.get_json(silent=True) or {}
        sent_at = payload.get("sent_at")
        try:
            if sent_at is not None and abs(time.time() - float(sent_at)) > 30:
                return jsonify({"ok": False, "error": "Stale collector payload."}), 408
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Invalid sent_at."}), 400
        accepted = ingest_local_candles(payload)
        if not accepted:
            return jsonify({"ok": False, "error": "No supported closed candle data found."}), 422
        return jsonify({"ok": True, "accepted": accepted, "status": local_stream_status()})

    @app.route("/quotex/stream-status", methods=["GET"])
    def quotex_stream_status():
        return jsonify(local_stream_status())

    return app
