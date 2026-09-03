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
    """Require score, MTF alignment, role reversal, and a 1m entry trigger."""
    if profile["score"] < CONFIG.min_score:
        return False
    if not profile["higher_timeframe_trend"]:
        return False
    if not profile["role_reversal_confirmation"]:
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
            "বুলিশ MMC: 15m ও 5m ট্রেন্ড একমত, breakout→retest role reversal নিশ্চিত, 1m এন্ট্রি ট্রিগার নিশ্চিত",
        )
    if sell_valid and sell > buy:
        return Signal(
            "SELL",
            buy,
            sell,
            "বেয়ারিশ MMC: 15m ও 5m ট্রেন্ড একমত, breakout→retest role reversal নিশ্চিত, 1m এন্ট্রি ট্রিগার নিশ্চিত",
        )
    if buy >= CONFIG.min_score or sell >= CONFIG.min_score:
        return Signal(
            "NO_TRADE",
            buy,
            sell,
            "স্কোর নির্ধারিত সীমায় পৌঁছেছে, কিন্তু MTF, role reversal, এন্ট্রি ট্রিগার বা মার্কেট স্ট্রাকচারে অসঙ্গতি আছে",
        )
    return Signal("NO_TRADE", buy, sell, "যথেষ্ট MMC কনফার্মেশন পাওয়া যায়নি")
