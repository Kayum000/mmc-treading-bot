"""Minimal on-demand web UI: selected Forex pair -> GET SIGNAL."""
from __future__ import annotations

import os
import time
from flask import Flask, render_template, request

from signals.get_signal import get_signal
from data.twelve_data_forex import fetch_api_usage, get_credit_usage

app = Flask(__name__)
PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "GBP/CHF",
    "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY", "EUR/AUD", "GBP/AUD",
    "AUD/CAD", "NZD/CAD",
]

_USAGE_CACHE = {"data": None, "at": 0.0}


def _find_number(obj, names):
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_norm = str(key).lower().replace("-", "_")
            if key_norm in names and isinstance(value, (int, float)):
                return int(value)
        for value in obj.values():
            found = _find_number(value, names)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_number(value, names)
            if found is not None:
                return found
    return None


def _usage_view():
    """Use real Twelve Data usage, cached for 60 seconds to avoid polling."""
    now = time.time()
    if now - _USAGE_CACHE["at"] >= 60 or _USAGE_CACHE["data"] is None:
        try:
            _USAGE_CACHE["data"] = fetch_api_usage()
            _USAGE_CACHE["at"] = now
        except Exception:
            pass

    payload = _USAGE_CACHE["data"]
    daily_left = None
    daily_limit = None
    if payload:
        daily_left = _find_number(payload, {"daily_credits_left", "daily_left", "daily_remaining", "credits_left"})
        daily_limit = _find_number(payload, {"daily_credits", "daily_limit", "daily_quota"})

    minute = get_credit_usage()
    return {
        "daily_left": daily_left,
        "daily_limit": daily_limit or (800 if daily_left is not None else None),
        "minute_left": minute.get("left"),
        "minute_limit": minute.get("limit"),
    }


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    pair = request.form.get("pair", PAIRS[0])
    if request.method == "POST":
        try:
            result = get_signal(pair)
        except Exception as exc:
            error = str(exc)
    usage = _usage_view()
    return render_template("index.html", pairs=PAIRS, pair=pair, result=result, error=error, usage=usage)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
