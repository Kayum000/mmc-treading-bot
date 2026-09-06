"""Compatibility signal wrapper for the canonical single-timeframe MMC engine.

The application uses ``signals/get_signal.py`` as its live entry point.  This
small wrapper intentionally accepts only one completed 1-minute frame and
never performs multi-timeframe analysis.
"""
from __future__ import annotations

import pandas as pd

from strategy.mmc import generate_signal


def build_signal(frames: dict[str, pd.DataFrame]):
    """Run the canonical MMC engine on the supplied closed 1-minute frame."""
    frame = frames.get("1m")
    if frame is None:
        raise ValueError("Missing required 1m timeframe")
    return generate_signal(frame)
