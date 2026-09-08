"""Flask route for the 20-25 second running-candle entry window."""
from __future__ import annotations

from flask import jsonify, request, session

from signals.running_entry import get_running_signal
from performance import record_signal


def register(app):
    @app.route("/running-signal", methods=["GET"])
    def running_signal():
        mode = session.get("selected_mode", "").strip().lower()
        pair = session.get("selected_pair", "").strip().upper()
        if not mode or not pair:
            return jsonify({"ok": False, "unselected": True, "error": "প্রথমে একটি মার্কেট নির্বাচন করুন।"}), 400
        try:
            result = get_running_signal(pair, mode)
            if result.get("signal") in {"BUY", "SELL"}:
                record_signal(result)
            return jsonify(result)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    return app
