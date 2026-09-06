"""Historical backtest for the canonical single-timeframe clean MMC strategy.

Input is a 1-minute OHLCV CSV. No higher-timeframe resampling or MTF
confirmation is used, so the backtest follows the same strategy path as live
signals and does not consume market-data API credits.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from strategy.mmc import generate_signal, level_for_side


BUCKETS = ((5, 6, "5-6"), (7, 8, "7-8"), (9, 10, "9-10"), (11, 99, "11+"))


def _load_1m_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    aliases = {"datetime": "timestamp", "date": "timestamp", "time": "timestamp"}
    for old, new in aliases.items():
        if "timestamp" not in df.columns and old in df.columns:
            df = df.rename(columns={old: "timestamp"})
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing CSV columns: {sorted(missing)}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    if df.empty:
        raise ValueError("CSV contains no valid OHLC rows")
    return df


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
    rows: list[dict[str, object]] = []
    minimum = 23
    for i in range(minimum - 1, len(df_1m) - 1):
        frame = df_1m.iloc[: i + 1].copy()
        result = generate_signal(frame)
        if result.action not in {"BUY", "SELL"}:
            continue
        level = level_for_side(frame, result.action)
        if level is None:
            continue
        entry_close = float(df_1m["close"].iloc[i])
        next_close = float(df_1m["close"].iloc[i + 1])
        score = result.buy_score if result.action == "BUY" else result.sell_score
        rows.append({
            "signal_time_utc": df_1m["timestamp"].iloc[i].isoformat(),
            "entry_time_utc": df_1m["timestamp"].iloc[i + 1].isoformat(),
            "action": result.action,
            "buy_score": result.buy_score,
            "sell_score": result.sell_score,
            "signal_score": score,
            "score_bucket": _bucket(score),
            "level_type": level[0],
            "level_price": level[1],
            "entry_close": entry_close,
            "next_close": next_close,
            "outcome": _outcome(result.action, entry_close, next_close),
        })

    trades = pd.DataFrame(rows)
    if trades.empty:
        return trades, {"signals": 0, "wins": 0, "losses": 0, "draws": 0, "accuracy_pct": None}
    wins = int((trades["outcome"] == "WIN").sum())
    losses = int((trades["outcome"] == "LOSS").sum())
    draws = int((trades["outcome"] == "DRAW").sum())
    decided = wins + losses
    return trades, {
        "signals": int(len(trades)), "wins": wins, "losses": losses, "draws": draws,
        "accuracy_pct": round(wins / decided * 100, 2) if decided else None,
    }


def build_report(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = ["score_bucket", "signals", "wins", "losses", "draws", "accuracy_pct"]
    if trades.empty:
        empty = pd.DataFrame(columns=columns)
        return empty, empty.copy()

    def aggregate(grouped) -> pd.DataFrame:
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
    parser = argparse.ArgumentParser(description="Backtest clean MMC on historical 1m OHLC data")
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
