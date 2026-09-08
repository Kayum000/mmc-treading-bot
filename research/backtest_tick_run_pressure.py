"""Research backtest for Tick-Run Pressure Continuation.

Run locally with the uploaded Dukascopy-style tick JSON converted to a DataFrame.
The grid is intentionally simple: run length x imbalance threshold. Results must
be validated on additional unseen days before any live deployment.
"""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
from strategy.tick_run_pressure import backtest_labels


def load_json(path: str) -> pd.DataFrame:
    return pd.DataFrame(json.loads(Path(path).read_text()))


def run(path: str) -> pd.DataFrame:
    ticks = load_json(path)
    rows = []
    for run_length in [4, 5, 6, 8, 10]:
        for threshold in [0.50, 0.60, 0.70]:
            x = backtest_labels(ticks, run_length, threshold)
            q = x[x.signal != "HOLD"]
            decided = q[q.future_direction != 0]
            acc = float(decided.correct.mean()) if len(decided) else float("nan")
            rows.append({
                "run_length": run_length,
                "imbalance_threshold": threshold,
                "signals": len(q),
                "decided": len(decided),
                "accuracy": acc,
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    print(run(args.path).to_string(index=False))
