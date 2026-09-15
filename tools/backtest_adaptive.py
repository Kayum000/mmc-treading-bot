"""Backtest the Real-Market adaptive strategy.

Usage:
  python tools/backtest_adaptive.py --csv quotex_real.csv
  python tools/backtest_adaptive.py --symbol AUDCAD --limit 1000

CSV columns: timestamp,open,high,low,close
The --symbol mode uses BiQuote only as a data-availability sanity benchmark;
use a Quotex-exported/captured CSV for a true Quotex backtest.
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
import pandas as pd

from strategy.adaptive_real import backtest_adaptive


def load_biquote(symbol: str, limit: int) -> pd.DataFrame:
    url = f"https://biquote.io/api/{urllib.parse.quote(symbol.upper())}/ohlc?interval=1m&limit={min(max(limit, 60), 1000)}"
    with urllib.request.urlopen(url, timeout=20) as r:
        payload = json.load(r)
    rows = payload.get("bars", []) if isinstance(payload, dict) else []
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No BiQuote candles returned")
    return pd.DataFrame({
        "timestamp": pd.to_datetime(df["openTime"], utc=True),
        "open": pd.to_numeric(df["open"], errors="coerce"),
        "high": pd.to_numeric(df["high"], errors="coerce"),
        "low": pd.to_numeric(df["low"], errors="coerce"),
        "close": pd.to_numeric(df["close"], errors="coerce"),
    }).dropna().sort_values("timestamp").reset_index(drop=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv")
    p.add_argument("--symbol", default="AUDCAD")
    p.add_argument("--limit", type=int, default=1000)
    args = p.parse_args()
    if args.csv:
        df = pd.read_csv(args.csv)
    else:
        df = load_biquote(args.symbol, args.limit)
        print("WARNING: BiQuote benchmark; this is NOT a Quotex execution-feed backtest.")
    result = backtest_adaptive(df)
    print(json.dumps({k: v for k, v in result.items() if k != "trades_df"}, indent=2, default=str))


if __name__ == "__main__":
    main()
