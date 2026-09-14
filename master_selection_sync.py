"""Keep market selection centralized on the Master device."""
from __future__ import annotations

import time
from flask import jsonify, request, session
from master_access import _is_master
from master_store import store


def init_master_selection_sync(app) -> None:
    @app.before_request
    def _master_selection_guard():
        # A Viewer/Trusted device must follow the current Master selection.
        # Keep its Flask session synchronized from the central state so the
        # existing /master/signal, /auto-signal, news and market-status routes
        # can work without granting the Viewer permission to change markets.
        if request.path == "/master/status" and request.method == "GET":
            if session.get("authenticated"):
                state = store.get_state() if store.enabled else {}
                mode = str(state.get("mode", "")).strip().lower()
                pair = str(state.get("pair", "")).strip().upper()
                if mode and pair:
                    session["selected_mode"] = mode
                    session["selected_pair"] = pair
            return None

        if request.path != "/select-market" or request.method != "POST": return None
        if not session.get("authenticated"): return None
        if not _is_master():
            state = store.get_state() if store.enabled else {}
            return jsonify({"ok":False,"error":"শুধু MASTER / MAIN PANEL থেকে market change করা যাবে।","master_mode":state.get("mode",""),"master_pair":state.get("pair","")}),403
        mode=str(request.form.get("mode","")).strip().lower(); pair=str(request.form.get("pair","")).strip().upper()
        from web.app import REAL_PAIRS, QUOTEX_OTC_PAIRS
        valid_pairs = REAL_PAIRS if mode == "real" else QUOTEX_OTC_PAIRS if mode == "quotex_otc" else []
        if pair not in valid_pairs: return jsonify({"ok":False,"error":"অবৈধ মার্কেট।"}),400
        session["selected_mode"]=mode; session["selected_pair"]=pair
        if store.enabled: store.update_selection(mode,pair,time.time())
        return jsonify({"ok":True,"mode":mode,"pair":pair,"role":"MASTER"})
