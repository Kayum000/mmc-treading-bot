"""Historical backtest for the live MMC 30m/15m/5m + 1m entry logic.

Input is a 1-minute OHLCV CSV. Higher timeframes are resampled locally, so the
backtest does not call the live API and does not consume API credits.

The result is intentionally descriptive: it measures historical outcomes and
does not guarantee future accuracy.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from strategy.signal import confirm_1m_entry, generate_signal


BUCKETS = ((12, 14, "12-14"), (15, 17, "15-17"), (18, 21, "18-21"), (22, 10**9, "22+"))


def _load_1m_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    aliases = {"datetime": "timestamp", "date": "timestamp", "time": "timestamp"}
    for old, new in aliases.items():
        if "timestamp" not in df.columns and old in df.columns:
            df = df.rename(columns={old: new})
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing CSV columns: {sorted(missing)}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df = df.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")
    if df.empty:
        raise ValueError("CSV contains no valid OHLC rows")
    return df


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    # Market-feed timestamps are treated as candle-open timestamps. A 5m
    # candle stamped 10:00 therefore covers 10:00..10:04 and is usable at
    # 10:04, without looking into the future.
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    out = df.resample(rule, label="left", closed="left").agg(agg)
    return out.dropna(subset=["open", "high", "low", "close"])


def _bucket(score: int) -> str:
    for low, high, label in BUCKETS:
        if low <= score <= high:
            return label
    return "other"


def _outcome(side: str, entry_close: float, next_close: float) -> str:
    if next_close > entry_close:
        return "WIN" if side == "BUY" else "LOSS"
    if next_close < entry_close:
        return "WIN" if side == "SELL" else "LOSS"
    return "DRAW"


def run_backtest(df_1m: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    frames = {
        "1m": df_1m,
        "5m": _resample(df_1m, "5min"),
        "15m": _resample(df_1m, "15min"),
        "30m": _resample(df_1m, "30min"),
    }

    rows: list[dict[str, object]] = []
    # Need enough 30m candles for EMA50 and one future 1m candle for outcome.
    start = 0
    for i in range(len(df_1m) - 1):
        ts = df_1m.index[i]
        if ts not in frames["1m"].index:
            continue
        f30 = frames["30m"].loc[:ts]
        f15 = frames["15m"].loc[:ts]
        f5 = frames["5m"].loc[:ts]
        if len(f30) < 50 or len(f15) < 50:
            continue

        candidate = generate_signal({"30m": f30, "15m": f15, "5m": f5})
        final = confirm_1m_entry(candidate, frames["1m"].iloc[: i + 1])
        if final.action not in {"BUY", "SELL"}:
            continue

        next_close = float(df_1m["close"].iloc[i + 1])
        entry_close = float(df_1m["close"].iloc[i])
        score = final.buy_score if final.action == "BUY" else final.sell_score
        rows.append(
            {
                "signal_time_utc": ts.isoformat(),
                "entry_time_utc": df_1m.index[i + 1].isoformat(),
                "action": final.action,
                "buy_score": final.buy_score,
                "sell_score": final.sell_score,
                "signal_score": score,
                "score_bucket": _bucket(score),
                "entry_close": entry_close,
                "next_close": next_close,
                "outcome": _outcome(final.action, entry_close, next_close),
            }
        )

    trades = pd.DataFrame(rows)
    if trades.empty:
        summary = {"signals": 0, "wins": 0, "losses": 0, "draws": 0, "accuracy_pct": None}
        return trades, summary

    wins = int((trades["outcome"] == "WIN").sum())
    losses = int((trades["outcome"] == "LOSS").sum())
    draws = int((trades["outcome"] == "DRAW").sum())
    decided = wins + losses
    summary = {
        "signals": int(len(trades)),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "accuracy_pct": round(wins / decided * 100, 2) if decided else None,
    }
    return trades, summary


def build_report(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if trades.empty:
        empty = pd.DataFrame(columns=["score_bucket", "signals", "wins", "losses", "draws", "accuracy_pct"])
        return empty, empty.copy()

    def aggregate(grouped: pd.core.groupby.generic.DataFrameGroupBy) -> pd.DataFrame:
        out = grouped.agg(
            signals=("outcome", "size"),
            wins=("outcome", lambda s: int((s == "WIN").sum())),
            losses=("outcome", lambda s: int((s == "LOSS").sum())),
            draws=("outcome", lambda s: int((s == "DRAW").sum())),
        ).reset_index()
        decided = out["wins"] + out["losses"]
        out["accuracy_pct"] = (out["wins"] / decided.replace(0, pd.NA) * 100).round(2)
        return out

    by_score = aggregate(trades.groupby("score_bucket", sort=False))
    by_direction = aggregate(trades.groupby("action", sort=False)).rename(columns={"action": "direction"})
    return by_score, by_direction


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest MMC signals on historical 1m OHLC data")
    parser.add_argument("csv", help="1-minute OHLC CSV path")
    parser.add_argument("--out", default="backtest_results", help="Output directory")
    args = parser.parse_args()

    df = _load_1m_csv(args.csv)
    trades, summary = run_backtest(df)
    by_score, by_direction = build_report(trades)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out / "signals.csv", index=False)
    by_score.to_csv(out / "score_report.csv", index=False)
    by_direction.to_csv(out / "direction_report.csv", index=False)

    print("MMC BACKTEST")
    print(f"Signals: {summary['signals']}")
    print(f"Wins: {summary['wins']} | Losses: {summary['losses']} | Draws: {summary['draws']}")
    print(f"Accuracy (wins / wins+losses): {summary['accuracy_pct']}%")
    print("\nScore buckets:")
    print(by_score.to_string(index=False) if not by_score.empty else "No confirmed signals")
    print(f"\nReports written to: {out.resolve()}")


if __name__ == "__main__":
    main()
