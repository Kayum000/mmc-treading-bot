"""Research-only TickFlow backtest.

Scores the current TickFlow conditions on minute-aggregated EURUSD tick data.
No future values are used in features; future midpoint direction is only the label.
"""
from __future__ import annotations
import json
import sys
import numpy as np
import pandas as pd


def build(path: str) -> pd.DataFrame:
    x = pd.DataFrame(json.load(open(path, "r", encoding="utf-8")))
    x["timestamp"] = pd.to_datetime(x["timestamp"], unit="ms", utc=True)
    x["mid"] = (x["askPrice"] + x["bidPrice"]) / 2.0
    x["spread"] = x["askPrice"] - x["bidPrice"]
    den = (x["bidVolume"] + x["askVolume"]).replace(0, np.nan)
    x["imbalance"] = ((x["bidVolume"] - x["askVolume"]) / den).fillna(0.0)
    x["tick_move"] = np.sign(x["mid"].diff()).fillna(0.0)
    m = x.set_index("timestamp").resample("1min").agg(
        mid=("mid", "last"), spread=("spread", "mean"),
        imbalance=("imbalance", "mean"), tick_move=("tick_move", "sum"),
        ticks=("mid", "size"),
    ).dropna(subset=["mid"])
    m["persist"] = m["imbalance"].rolling(3).mean()
    m["pressure"] = m["tick_move"].rolling(3).sum()
    m["activity_z"] = m["ticks"].rolling(20).apply(
        lambda a: (a[-1] - a.mean()) / (a.std() or 1.0), raw=True
    )
    m["spread_z"] = m["spread"].rolling(20).apply(
        lambda a: (a[-1] - a.mean()) / (a.std() or 1.0), raw=True
    )
    return m.dropna()


def score(m: pd.DataFrame, horizon: int, imb: float, persist: float) -> tuple[int, float]:
    buy = (m.imbalance >= imb) & (m.persist >= persist) & (m.pressure > 0)
    sell = (m.imbalance <= -imb) & (m.persist <= -persist) & (m.pressure < 0)
    valid = (m.spread_z < 2.5) & (m.activity_z > -1.5)
    sig = np.where(valid & buy, 1, np.where(valid & sell, -1, 0))
    future = m.mid.shift(-horizon) - m.mid
    mask = (sig != 0) & future.notna()
    if not mask.any():
        return 0, float("nan")
    accuracy = (np.sign(future[mask].to_numpy()) == sig[mask]).mean()
    return int(mask.sum()), float(accuracy)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python research/backtest_tickflow.py TICK_JSON")
    m = build(sys.argv[1])
    for h in (1, 2, 3, 5):
        for a, b in ((0.28, 0.18), (0.35, 0.22), (0.40, 0.25), (0.50, 0.30)):
            n, acc = score(m, h, a, b)
            print(f"h={h}m imbalance={a:.2f} persistence={b:.2f} signals={n} accuracy={acc:.4f}")
