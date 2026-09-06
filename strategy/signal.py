from dataclasses import dataclass
import pandas as pd

from config import CONFIG
from strategy.multi_timeframe import multi_timeframe_score, confirmation_profile
from strategy.mmc import liquidity_sweep, displacement, market_structure, strong_level_rejection


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
        f"বিপরীত BOS নেই: {'ঠিক আছে' if not profile['opposite_structure'] else 'মেলেনি'}",
    ]
    failed = [item for item in checks if "মেলেনি" in item]
    if failed:
        return "পরিষ্কার MMC শর্ত পূরণ হয়নি: " + "; ".join(failed) + "."
    return "দুই দিকের কাঠামো স্পষ্ট নয়; তাই NO_TRADE।"


def generate_signal(frames: dict[str, pd.DataFrame]) -> Signal:
    """Pure MMC MTF setup: 30m/15m structure -> 5m setup."""
    required = {"30m", "15m", "5m"}
    missing = required.difference(frames)
    if missing:
        raise ValueError(f"Missing timeframes: {sorted(missing)}")

    buy = multi_timeframe_score(frames, "buy")
    sell = multi_timeframe_score(frames, "sell")
    buy_profile = confirmation_profile(frames, "buy")
    sell_profile = confirmation_profile(frames, "sell")
    buy_valid = _is_valid_setup(buy_profile)
    sell_valid = _is_valid_setup(sell_profile)

    if buy_valid and not sell_valid:
        return Signal(
            "BUY", buy, sell,
            "পরিষ্কার বুলিশ MMC: ৩০m ও ১৫m একই bullish কাঠামো দেখাচ্ছে এবং ৫m-এ একই দিকে sweep + displacement setup আছে। পরবর্তী 1m entry-এর জন্য অনুমোদিত।",
        )
    if sell_valid and not buy_valid:
        return Signal(
            "SELL", buy, sell,
            "পরিষ্কার bearish MMC: ৩০m ও ১৫m একই bearish কাঠামো দেখাচ্ছে এবং ৫m-এ একই দিকে sweep + displacement setup আছে। পরবর্তী 1m entry-এর জন্য অনুমোদিত।",
        )
    if buy_valid and sell_valid:
        return Signal("NO_TRADE", buy, sell, "BUY ও SELL—দুই দিকের MMC কাঠামো একসঙ্গে বৈধ; তাই দ্ব্যর্থক অবস্থায় entry নেই।")

    diagnostic = _diagnostic_reason(buy_profile, "buy") if buy >= sell else _diagnostic_reason(sell_profile, "sell")
    return Signal("NO_TRADE", buy, sell, diagnostic)


def _recent_confirmation(df: pd.DataFrame, side: str) -> bool:
    """Require a second MMC confirmation before the latest rejection candle."""
    if len(df) < 3:
        return False
    start = max(1, len(df) - 3)
    end = len(df) - 1
    for i in range(start, end):
        part = df.iloc[:i + 1]
        structure = market_structure(part, CONFIG.swing_lookback)
        sweep = liquidity_sweep(part, CONFIG.sweep_lookback)
        impulse = displacement(part)
        if side == "buy" and (
            structure == "bullish_bos" or sweep == "buy_side_rejection" or impulse == "bullish"
        ):
            return True
        if side == "sell" and (
            structure == "bearish_bos" or sweep == "sell_side_rejection" or impulse == "bearish"
        ):
            return True
    return False


def generate_1m_signal(df: pd.DataFrame) -> Signal:
    """Pure 1m MMC entry: key-level rejection + liquidity/impulse confirmation.

    No EMA or momentum indicator is used here. Resistance rejection creates a
    SELL setup; support rejection creates a BUY setup. The latest closed candle
    must reject the level, and a second same-direction MMC confirmation must
    already exist in the recent closed candles.
    """
    if df is None or df.empty:
        return Signal("NO_TRADE", 0, 0, "১ মিনিটের বাজারের তথ্য পাওয়া যায়নি।")
    if len(df) < max(CONFIG.sweep_lookback + 1, CONFIG.swing_lookback + 3, 23):
        return Signal("NO_TRADE", 0, 0, "পরিষ্কার ১ মিনিটের MMC যাচাইয়ের জন্য পর্যাপ্ত বন্ধ ক্যান্ডেল নেই।")

    structure = market_structure(df, CONFIG.swing_lookback)
    sweep = liquidity_sweep(df, CONFIG.sweep_lookback)
    impulse = displacement(df)
    rejection = strong_level_rejection(df)

    buy_score = (
        2 * int(structure == "bullish_bos")
        + 2 * int(sweep == "buy_side_rejection")
        + int(impulse == "bullish")
        + 3 * int(rejection == "strong_support_rejection")
    )
    sell_score = (
        2 * int(structure == "bearish_bos")
        + 2 * int(sweep == "sell_side_rejection")
        + int(impulse == "bearish")
        + 3 * int(rejection == "strong_resistance_rejection")
    )

    buy_rejection = rejection == "strong_support_rejection"
    sell_rejection = rejection == "strong_resistance_rejection"
    buy_current_confirmation = sweep == "buy_side_rejection" or impulse == "bullish"
    sell_current_confirmation = sweep == "sell_side_rejection" or impulse == "bearish"
    buy_recent_confirmation = _recent_confirmation(df, "buy")
    sell_recent_confirmation = _recent_confirmation(df, "sell")

    buy_valid = buy_rejection and buy_current_confirmation and buy_recent_confirmation
    sell_valid = sell_rejection and sell_current_confirmation and sell_recent_confirmation

    if buy_valid and not sell_valid:
        return Signal(
            "BUY", buy_score, sell_score,
            "পরিষ্কার MMC BUY: গুরুত্বপূর্ণ support level-এ rejection হয়েছে, বর্তমান বন্ধ ক্যান্ডেলে bullish sweep/displacement confirmation আছে এবং আগের recent candles-এ আরও একটি bullish MMC confirmation রয়েছে। তাই পরবর্তী 1m candle BUY entry।",
        )
    if sell_valid and not buy_valid:
        return Signal(
            "SELL", buy_score, sell_score,
            "পরিষ্কার MMC SELL: গুরুত্বপূর্ণ resistance level-এ rejection হয়েছে, বর্তমান বন্ধ ক্যান্ডেলে bearish sweep/displacement confirmation আছে এবং আগের recent candles-এ আরও একটি bearish MMC confirmation রয়েছে। তাই পরবর্তী 1m candle SELL entry।",
        )
    if buy_valid and sell_valid:
        return Signal("NO_TRADE", buy_score, sell_score, "Support ও resistance—দুই দিকেই MMC setup বৈধ; তাই দ্ব্যর্থক অবস্থায় entry নেই।")

    return Signal(
        "NO_TRADE", buy_score, sell_score,
        "পরিষ্কার MMC entry নেই। শুধু level touch/rejection যথেষ্ট নয়; support/resistance rejection-এর সঙ্গে একই-direction sweep বা displacement এবং একটি recent confirmation প্রয়োজন।",
    )
