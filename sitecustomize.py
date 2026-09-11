"""Compatibility bootstrap for the legacy Market Status endpoint.

The page template still references the old ``market_status`` endpoint.  The
endpoint was removed while the visible Market Status panel was being rebuilt,
which caused Flask/Jinja to return HTTP 500 before the page could render.
Register a lightweight compatibility endpoint as soon as Flask creates the
application so the existing template remains valid.
"""
from __future__ import annotations


def _install_market_status_compat() -> None:
    try:
        from flask import Flask, jsonify, session
    except Exception:
        return

    original_init = Flask.__init__
    if getattr(Flask, "_mmc_market_status_compat", False):
        return

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        def market_status():
            mode = str(session.get("selected_mode", "")).strip().lower()
            pair = str(session.get("selected_pair", "")).strip().upper()
            is_otc = mode == "crypto"
            return jsonify({
                "ok": True,
                "pair": pair,
                "session": "24/7 OTC" if is_otc else "Forex Session",
                "activity": "HIGH" if is_otc else "MEDIUM",
                "activity_bn": "HIGH" if is_otc else "MEDIUM",
                "best_window_bn": "24/7 OTC Market" if is_otc else "London / New York overlap",
                "news_risk": "LOW",
                "news_risk_bn": "LOW",
                "next_news_time_utc": None,
            })

        self.add_url_rule("/market-status", "market_status", market_status, methods=["GET"])

    Flask.__init__ = patched_init
    Flask._mmc_market_status_compat = True


_install_market_status_compat()
