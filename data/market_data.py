from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ["open", "high", "low", "close"]


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLC columns: {missing}")
    for col in REQUIRED_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=REQUIRED_COLUMNS).reset_index(drop=True)
