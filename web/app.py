"""Minimal on-demand web UI: selected Forex pair -> GET SIGNAL."""
from __future__ import annotations

import os
from flask import Flask, render_template, request

from signals.get_signal import get_signal

app = Flask(__name__)
PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "GBP/CHF",
    "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY", "EUR/AUD", "GBP/AUD",
    "AUD/CAD", "NZD/CAD",
]

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
    return render_template("index.html", pairs=PAIRS, pair=pair, result=result, error=error)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
