"""Small safe Market Status endpoint used by the existing dashboard template."""
from __future__ import annotations

from flask import jsonify, session


def init_market_status(app) -> None:
    @app.route("/market-status", methods=["GET"])
    def market_status():
        mode = str(session.get("selected_mode", "")).strip().lower()
        pair = str(session.get("selected_pair", "")).strip().upper()
        if not pair or mode not in {"real", "quotex_otc"}:
            return jsonify({"ok": False, "pair": pair, "mode": mode})
        otc = mode == "quotex_otc"
        return jsonify({
            "ok": True,
            "pair": pair,
            "session": "24/7 OTC" if otc else "Forex Session",
            "activity": "HIGH" if otc else "MEDIUM",
            "activity_bn": "HIGH" if otc else "MEDIUM",
            "best_window_bn": "24/7 OTC Market" if otc else "London / New York overlap",
            "news_risk": "LOW",
            "news_risk_bn": "LOW",
            "next_news_time_utc": None,
        })
