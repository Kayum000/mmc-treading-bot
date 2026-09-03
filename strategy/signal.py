from dataclasses import dataclass
import pandas as pd

from config import CONFIG
from strategy.multi_timeframe import multi_timeframe_score, confirmation_profile
from strategy.mmc import liquidity_sweep, displacement, market_structure


@dataclass(frozen=True)
class Signal:
    action: str
    buy_score: int
    sell_score: int
    reason: str


def _is_valid_setup(profile: dict, side: str) -> bool:
    """Require score, higher-timeframe alignment, role reversal, and 5m trigger."""
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

    if profile["30m"]["score"] < 4:
        return False
    if profile["15m"]["score"] < 3:
        return False
    if profile["5m"]["score"] < 1:
        return False
    return True


def _diagnostic_reason(profile: dict, side: str) -> str:
    """Explain every final gate without changing the signal decision logic."""
    direction = "বিক্রির" if side == "sell" else "কেনার"
    opposite = "বিপরীত ঊর্ধ্বমুখী বাজার-গঠন পাওয়া যায়নি" if side == "sell" else "বিপরীত নিম্নমুখী বাজার-গঠন পাওয়া যায়নি"

    checks = [
        f"স্কোর সীমা: {'ঠিক আছে' if profile['score'] >= CONFIG.min_score else 'মেলেনি'} ({profile['score']}/{CONFIG.min_score})",
        f"৩০ ও ১৫ মিনিটের দিক একমত: {'ঠিক আছে' if profile['higher_timeframe_trend'] else 'মেলেনি'}",
        f"ভাঙা স্তরের পুনঃপরীক্ষা ও নতুন ভূমিকা: {'ঠিক আছে' if profile['role_reversal_confirmation'] else 'মেলেনি'}",
        f"৫ মিনিটের {direction} প্রবেশের সংকেত: {'ঠিক আছে' if profile['entry_trigger'] else 'মেলেনি'}",
        f"{opposite}: {'ঠিক আছে' if not profile['opposite_structure'] else 'মেলেনি'}",
        f"৩০ মিনিটের স্কোর: {'ঠিক আছে' if profile['30m']['score'] >= 4 else 'মেলেনি'} ({profile['30m']['score']}/4 ন্যূনতম)",
        f"১৫ মিনিটের স্কোর: {'ঠিক আছে' if profile['15m']['score'] >= 3 else 'মেলেনি'} ({profile['15m']['score']}/3 ন্যূনতম)",
        f"৫ মিনিটের স্কোর: {'ঠিক আছে' if profile['5m']['score'] >= 1 else 'মেলেনি'} ({profile['5m']['score']}/1 ন্যূনতম)",
    ]
    failed = [item for item in checks if "মেলেনি" in item]
    status = "সব চূড়ান্ত শর্ত পূরণ হয়েছে, কিন্তু অন্য দিকের স্কোর বেশি হওয়ায় এই দিকে সিগন্যাল দেওয়া হয়নি।" if not failed else "যে শর্তগুলোতে সমস্যা হয়েছে: " + "; ".join(failed) + "."
    return "স্কোর নির্ধারিত সীমায় পৌঁছেছে। বিস্তারিত যাচাই — " + " | ".join(checks) + "। " + status


def generate_signal(frames: dict[str, pd.DataFrame]) -> Signal:
    required = {"30m", "15m", "5m"}
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
            "বুলিশ MMC: ৩০ মিনিট ও ১৫ মিনিটের বাজারের দিক ঊর্ধ্বমুখী এবং একমত। আগের প্রতিরোধের স্তর ভেঙে দাম আবার সেই স্তরে ফিরে এসে সেটিকে সমর্থন হিসেবে ধরে রেখেছে। ৫ মিনিটে কেনার প্রবেশের সংকেতও নিশ্চিত হয়েছে।",
        )
    if sell_valid and sell > buy:
        return Signal(
            "SELL",
            buy,
            sell,
            "বেয়ারিশ MMC: ৩০ মিনিট ও ১৫ মিনিটের বাজারের দিক নিম্নমুখী এবং একমত। আগের সমর্থনের স্তর ভেঙে দাম আবার সেই স্তরে ফিরে এসে সেটিকে প্রতিরোধ হিসেবে ধরে রেখেছে। ৫ মিনিটে বিক্রির প্রবেশের সংকেতও নিশ্চিত হয়েছে।",
        )
    if buy >= CONFIG.min_score or sell >= CONFIG.min_score:
        diagnostic = _diagnostic_reason(buy_profile, "buy") if buy >= sell else _diagnostic_reason(sell_profile, "sell")
        return Signal("NO_TRADE", buy, sell, diagnostic)
    return Signal("NO_TRADE", buy, sell, "যথেষ্ট MMC নিশ্চিতকরণ পাওয়া যায়নি। বাজারের দিক, বাজারের গঠন এবং ৫ মিনিটের প্রবেশের সংকেত এখনও যথেষ্ট শক্তিশালী নয়।")


def confirm_1m_entry(signal: Signal, df_1m: pd.DataFrame) -> Signal:
    """Use the latest closed 1m candle as the final entry trigger.

    The 30m/15m/5m MMC score is unchanged. A trade is only kept when the
    latest closed 1m candle confirms the already-selected direction via a
    matching BOS, liquidity sweep/reclaim, or displacement candle.
    """
    if signal.action not in {"BUY", "SELL"}:
        return signal
    if df_1m is None or df_1m.empty:
        return Signal(signal.action, signal.buy_score, signal.sell_score, signal.reason + " ১ মিনিটের প্রবেশ যাচাইয়ের জন্য ডেটা পাওয়া যায়নি; ট্রেড বাতিল করা হয়েছে।")

    side = "buy" if signal.action == "BUY" else "sell"
    bos = market_structure(df_1m, lookback=3)
    sweep = liquidity_sweep(df_1m, lookback=10)
    move = displacement(df_1m)

    confirmed = (
        (side == "buy" and (bos == "bullish_bos" or sweep == "buy_side_rejection" or move == "bullish"))
        or (side == "sell" and (bos == "bearish_bos" or sweep == "sell_side_rejection" or move == "bearish"))
    )
    if confirmed:
        return Signal(
            signal.action,
            signal.buy_score,
            signal.sell_score,
            signal.reason + " ১ মিনিটের শেষ বন্ধ ক্যান্ডেলেও একই দিকের প্রবেশ ট্রিগার নিশ্চিত হয়েছে; পরবর্তী ১ মিনিটের ক্যান্ডেল এন্ট্রির জন্য প্রস্তুত।",
        )

    return Signal(
        "NO_TRADE",
        signal.buy_score,
        signal.sell_score,
        signal.reason + " ১ মিনিটের শেষ বন্ধ ক্যান্ডেলে একই দিকের BOS, liquidity sweep/reclaim বা displacement নিশ্চিত হয়নি; তাই পরবর্তী ১ মিনিটের ক্যান্ডেলে এন্ট্রি দেওয়া হয়নি।",
    )
