from dataclasses import dataclass
import pandas as pd

from config import CONFIG
from strategy.multi_timeframe import multi_timeframe_score, confirmation_profile
from strategy.mmc_clean import liquidity_sweep, displacement, market_structure, strong_level_rejection


@dataclass(frozen=True)
class Signal:
    action: str
    buy_score: int
    sell_score: int
    reason: str


def _is_valid_setup(profile: dict) -> bool:
    return bool(
        profile["higher_timeframe_trend"]
        and profile["entry_trigger"]
        and not profile["opposite_structure"]
    )


def _diagnostic_reason(profile: dict, side: str) -> str:
    direction = "বিক্রির" if side == "sell" else "কেনার"
    checks = [
        f"৩০ ও ১৫ মিনিটের কাঠামো একমত: {'ঠিক আছে' if profile['higher_timeframe_trend'] else 'মেলেনি'}",
        f"৫ মিনিটের {direction} setup: {'ঠিক আছে' if profile['entry_trigger'] else 'মেলেনি'}",
        f"বিপরীত কাঠামো নেই: {'ঠিক আছে' if not profile['opposite_structure'] else 'মেলেনি'}",
    ]
    failed = [item for item in checks if "মেলেনি" in item]
    return "পরিষ্কার MMC শর্ত পূরণ হয়নি: " + "; ".join(failed) + "." if failed else "দুই দিকের কাঠামো স্পষ্ট নয়; তাই NO_TRADE।"


def _recent_confirmation(df: pd.DataFrame, side: str) -> bool:
    """Require prior same-direction MMC evidence before the latest 1m trigger."""
    if df is None or len(df) < 4:
        return False
    start = max(1, len(df) - 4)
    end = len(df) - 1
    for i in range(start, end):
        part = df.iloc[:i + 1]
        structure = market_structure(part, CONFIG.swing_lookback)
        sweep = liquidity_sweep(part, CONFIG.sweep_lookback)
        impulse = displacement(part)
        if side == "buy" and (structure == "bullish_bos" or sweep == "buy_side_rejection" or impulse == "bullish"):
            return True
        if side == "sell" and (structure == "bearish_bos" or sweep == "sell_side_rejection" or impulse == "bearish"):
            return True
    return False


def generate_1m_signal(df: pd.DataFrame) -> Signal:
    """Pure MMC 1m entry; no EMA, RSI, MACD or non-MMC indicator."""
    if df is None or df.empty:
        return Signal("NO_TRADE", 0, 0, "১ মিনিটের বাজারের তথ্য পাওয়া যায়নি।")
    minimum = max(CONFIG.sweep_lookback + 1, CONFIG.level_lookback + 5, 23)
    if len(df) < minimum:
        return Signal("NO_TRADE", 0, 0, "পরিষ্কার ১ মিনিটের MMC যাচাইয়ের জন্য পর্যাপ্ত বন্ধ ক্যান্ডেল নেই।")

    structure = market_structure(df, CONFIG.swing_lookback)
    sweep = liquidity_sweep(df, CONFIG.sweep_lookback)
    impulse = displacement(df)
    rejection = strong_level_rejection(df, CONFIG.level_lookback)

    buy_score = 2 * int(structure == "bullish_bos") + 2 * int(sweep == "buy_side_rejection") + int(impulse == "bullish") + 3 * int(rejection == "strong_support_rejection")
    sell_score = 2 * int(structure == "bearish_bos") + 2 * int(sweep == "sell_side_rejection") + int(impulse == "bearish") + 3 * int(rejection == "strong_resistance_rejection")

    buy_valid = (
        rejection == "strong_support_rejection"
        and (sweep == "buy_side_rejection" or impulse == "bullish")
        and _recent_confirmation(df, "buy")
    )
    sell_valid = (
        rejection == "strong_resistance_rejection"
        and (sweep == "sell_side_rejection" or impulse == "bearish")
        and _recent_confirmation(df, "sell")
    )

    if buy_valid and not sell_valid:
        return Signal("BUY", buy_score, sell_score, "পরিষ্কার MMC BUY: support rejection, bullish sweep/displacement এবং আগের একই-direction MMC confirmation আছে। পরবর্তী 1m candle entry।")
    if sell_valid and not buy_valid:
        return Signal("SELL", buy_score, sell_score, "পরিষ্কার MMC SELL: resistance rejection, bearish sweep/displacement এবং আগের একই-direction MMC confirmation আছে। পরবর্তী 1m candle entry।")
    if buy_valid and sell_valid:
        return Signal("NO_TRADE", buy_score, sell_score, "Support ও resistance—দুই দিকেই MMC setup একসঙ্গে বৈধ; তাই entry নেই।")
    return Signal("NO_TRADE", buy_score, sell_score, "শুধু level touch যথেষ্ট নয়। পরিষ্কার MMC rejection-এর সঙ্গে sweep/displacement এবং আগের একই-direction confirmation না থাকলে entry হবে না।")


def generate_signal(frames: dict[str, pd.DataFrame]) -> Signal:
    """Single pure-MMC path: 30m -> 15m -> 5m -> 1m -> next 1m candle."""
    required = {"30m", "15m", "5m", "1m"}
    missing = required.difference(frames)
    if missing:
        raise ValueError(f"Missing timeframes: {sorted(missing)}")

    buy = multi_timeframe_score(frames, "buy")
    sell = multi_timeframe_score(frames, "sell")
    buy_profile = confirmation_profile(frames, "buy")
    sell_profile = confirmation_profile(frames, "sell")
    buy_valid = _is_valid_setup(buy_profile)
    sell_valid = _is_valid_setup(sell_profile)
    entry_1m = generate_1m_signal(frames["1m"])

    if buy_valid and not sell_valid and entry_1m.action == "BUY":
        return Signal("BUY", buy + entry_1m.buy_score, sell + entry_1m.sell_score, "Pure MMC confirmed: 30m bullish structure → 15m bullish confirmation → 5m support rejection/sweep-displacement → 1m bullish entry confirmation. পরবর্তী 1m candle entry।")
    if sell_valid and not buy_valid and entry_1m.action == "SELL":
        return Signal("SELL", buy + entry_1m.buy_score, sell + entry_1m.sell_score, "Pure MMC confirmed: 30m bearish structure → 15m bearish confirmation → 5m resistance rejection/sweep-displacement → 1m bearish entry confirmation. পরবর্তী 1m candle entry।")
    if buy_valid and sell_valid:
        return Signal("NO_TRADE", buy + entry_1m.buy_score, sell + entry_1m.sell_score, "দুই দিকেই MMC MTF setup বৈধ বা বিরোধী; তাই entry নেই।")
    return Signal("NO_TRADE", buy + entry_1m.buy_score, sell + entry_1m.sell_score, "30m → 15m → 5m MMC chain বা 1m final confirmation সম্পূর্ণ হয়নি; তাই entry নেই।")
