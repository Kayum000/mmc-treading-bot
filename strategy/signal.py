from dataclasses import dataclass
import pandas as pd

from config import CONFIG
from strategy.multi_timeframe import multi_timeframe_score, confirmation_profile


@dataclass(frozen=True)
class Signal:
    action: str
    buy_score: int
    sell_score: int
    reason: str


def _is_valid_setup(profile: dict, side: str) -> bool:
    """Require score, higher-timeframe alignment, and a 1m entry trigger."""
    if profile["score"] < CONFIG.min_score:
        return False
    if not profile["higher_timeframe_trend"]:
        return False
    if not profile["entry_trigger"]:
        return False
    if profile["opposite_structure"]:
        return False

    # Prevent a signal from being carried almost entirely by one timeframe.
    if profile["15m"]["score"] < 4:
        return False
    if profile["5m"]["score"] < 3:
        return False
    if profile["1m"]["score"] < 1:
        return False
    return True


def generate_signal(frames: dict[str, pd.DataFrame]) -> Signal:
    required = {"15m", "5m", "1m"}
    missing = required.difference(frames)
    if missing:
        raise ValueError(f"Missing timeframes: {sorted(missing)}")

    buy = multi_timeframe_score(frames, "buy")
    sell = multi_timeframe_score(frames, "sell")
    buy_profile = confirmation_profile(frames, "buy")
    sell_profile = confirmation_profile(frames, "sell")

    buy_valid = _is_valid_setup(buy_profile, "buy")
    sell_valid = _is_valid_setup(sell_profile, "sell")

    if buy_valid and buy > sell:
        return Signal(
            "BUY",
            buy,
            sell,
            "Bullish MMC: 15m + 5m trend aligned, 1m entry trigger confirmed",
        )
    if sell_valid and sell > buy:
        return Signal(
            "SELL",
            buy,
            sell,
            "Bearish MMC: 15m + 5m trend aligned, 1m entry trigger confirmed",
        )
    if buy >= CONFIG.min_score or sell >= CONFIG.min_score:
        return Signal(
            "NO_TRADE",
            buy,
            sell,
            "Score reached threshold but MTF, trigger, or structure confirmation conflicted",
        )
    return Signal("NO_TRADE", buy, sell, "Insufficient MMC confirmation")
