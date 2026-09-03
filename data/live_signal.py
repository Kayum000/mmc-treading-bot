"""Signal pipeline for normalized multi-timeframe candle data."""
from __future__ import annotations

import pandas as pd

from strategy.signal import generate_signal


def build_signal(frames: dict[str, pd.DataFrame]):
    """Run the existing MMC/MTF engine on 30m, 15m and 5m OHLC frames."""
    required = {"30m", "15m", "5m"}
    missing = required.difference(frames)
    if missing:
        raise ValueError(f"Missing timeframes: {sorted(missing)}")
    return generate_signal({tf: frames[tf] for tf in ("30m", "15m", "5m")})
