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


def _diagnostic_reason(profile: dict, side: str) -> str:
    """Explain every final gate without changing the signal decision logic."""
    direction = "বিক্রির" if side == "sell" else "কেনার"
    opposite = "বিপরীত ঊর্ধ্বমুখী বাজার-গঠন পাওয়া যায়নি" if side == "sell" else "বিপরীত নিম্নমুখী বাজার-গঠন পাওয়া যায়নি"

    checks = [
        f"স্কোর সীমা: {'ঠিক আছে' if profile['score'] >= CONFIG.min_score else 'মেলেনি'} ({profile['score']}/{CONFIG.min_score})",
        f"১৫ ও ৫ মিনিটের দিক একমত: {'ঠিক আছে' if profile['higher_timeframe_trend'] else 'মেলেনি'}",
        f"ভাঙা স্তরের পুনঃপরীক্ষা ও নতুন ভূমিকা: {'ঠিক আছে' if profile['role_reversal_confirmation'] else 'মেলেনি'}",
        f"১ মিনিটের {direction} প্রবেশের সংকেত: {'ঠিক আছে' if profile['entry_trigger'] else 'মেলেনি'}",
        f"{opposite}: {'ঠিক আছে' if not profile['opposite_structure'] else 'মেলেনি'}",
        f"১৫ মিনিটের স্কোর: {'ঠিক আছে' if profile['15m']['score'] >= 4 else 'মেলেনি'} ({profile['15m']['score']}/4 ন্যূনতম)",
        f"৫ মিনিটের স্কোর: {'ঠিক আছে' if profile['5m']['score'] >= 3 else 'মেলেনি'} ({profile['5m']['score']}/3 ন্যূনতম)",
        f"১ মিনিটের স্কোর: {'ঠিক আছে' if profile['1m']['score'] >= 1 else 'মেলেনি'} ({profile['1m']['score']}/1 ন্যূনতম)",
    ]
    failed = [item for item in checks if "মেলেনি" in item]
    status = "সব চূড়ান্ত শর্ত পূরণ হয়েছে, কিন্তু অন্য দিকের স্কোর বেশি হওয়ায় এই দিকে সিগন্যাল দেওয়া হয়নি।" if not failed else "যে শর্তগুলোতে সমস্যা হয়েছে: " + "; ".join(failed) + "."
    return "স্কোর নির্ধারিত সীমায় পৌঁছেছে। বিস্তারিত যাচাই — " + " | ".join(checks) + "। " + status


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
            "বুলিশ MMC: ১৫ মিনিট ও ৫ মিনিটের বাজারের দিক ঊর্ধ্বমুখী এবং একমত। আগের প্রতিরোধের স্তর ভেঙে দাম আবার সেই স্তরে ফিরে এসে সেটিকে সমর্থন হিসেবে ধরে রেখেছে। ১ মিনিটে কেনার প্রবেশের সংকেতও নিশ্চিত হয়েছে।",
        )
    if sell_valid and sell > buy:
        return Signal(
            "SELL",
            buy,
            sell,
            "বেয়ারিশ MMC: ১৫ মিনিট ও ৫ মিনিটের বাজারের দিক নিম্নমুখী এবং একমত। আগের সমর্থনের স্তর ভেঙে দাম আবার সেই স্তরে ফিরে এসে সেটিকে প্রতিরোধ হিসেবে ধরে রেখেছে। ১ মিনিটে বিক্রির প্রবেশের সংকেতও নিশ্চিত হয়েছে।",
        )
    if buy >= CONFIG.min_score or sell >= CONFIG.min_score:
        if buy >= sell:
            diagnostic = _diagnostic_reason(buy_profile, "buy")
        else:
            diagnostic = _diagnostic_reason(sell_profile, "sell")
        return Signal("NO_TRADE", buy, sell, diagnostic)
    return Signal("NO_TRADE", buy, sell, "যথেষ্ট MMC নিশ্চিতকরণ পাওয়া যায়নি। বাজারের দিক, বাজারের গঠন এবং ১ মিনিটের প্রবেশের সংকেত এখনও যথেষ্ট শক্তিশালী নয়।")
