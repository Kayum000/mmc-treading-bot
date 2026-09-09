"""Keep market selection centralized on the Master device.

This layer sits beside the existing Master/Viewer access layer. It does not
change signal strategy logic; it only makes the selected market a shared
state and rejects Viewer-side market changes.
"""
from __future__ import annotations

import time

from flask import jsonify, request, session

from master_access import _is_master
from master_store import store


def init_master_selection_sync(app) -> None:
    @app.before_request
    def _master_selection_guard():
        if request.path != "/select-market" or request.method != "POST":
            return None
        if not session.get("authenticated"):
            return None

        if not _is_master():
            state = store.get_state() if store.enabled else {}
            return jsonify({
                "ok": False,
                "error": "শুধু MASTER / MAIN PANEL থেকে market change করা যাবে।",
                "master_mode": state.get("mode", ""),
                "master_pair": state.get("pair", ""),
            }), 403

        mode = str(request.form.get("mode", "")).strip().lower()
        pair = str(request.form.get("pair", "")).strip().upper()
        from web.app import REAL_PAIRS, CRYPTO_PAIRS
        valid_pairs = REAL_PAIRS if mode == "real" else CRYPTO_PAIRS if mode == "crypto" else []
        if pair not in valid_pairs:
            return jsonify({"ok": False, "error": "অবৈধ মার্কেট।"}), 400

        session["selected_mode"] = mode
        session["selected_pair"] = pair
        if store.enabled:
            store.update_selection(mode, pair, time.time())
        return jsonify({"ok": True, "mode": mode, "pair": pair, "role": "MASTER"})
