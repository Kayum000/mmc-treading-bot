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


def _is_valid_setup(profile: dict, side: str) -> bool:
    """Validate the MTF structure without using the MTF score as a gate."""
    if not profile["higher_timeframe_trend"]:
        return False
    if not profile["role_reversal_confirmation"]:
        return False
    if not profile["entry_trigger"]:
        return False
    if profile["opposite_structure"]:
        return False
    return True


def _diagnostic_reason(profile: dict, side: str) -> str:
    """Explain the structural gates without using score thresholds."""
    direction = "বিক্রির" if side == "sell" else "কেনার"
    opposite = "বিপরীত ঊর্ধ্বমুখী বাজার-গঠন পাওয়া যায়নি" if side == "sell" else "বিপরীত নিম্নমুখী বাজার-গঠন পাওয়া যায়নি"

    checks = [
        f"৩০ ও ১৫ মিনিটের দিক একমত: {'ঠিক আছে' if profile['higher_timeframe_trend'] else 'মেলেনি'}",
        f"ভাঙা স্তরের পুনঃপরীক্ষা/রিজেকশন: {'ঠিক আছে' if profile['role_reversal_confirmation'] else 'মেলেনি'}",
        f"৫ মিনিটের {direction} প্রবেশের সংকেত: {'ঠিক আছে' if profile['entry_trigger'] else 'মেলেনি'}",
        f"{opposite}: {'ঠিক আছে' if not profile['opposite_structure'] else 'মেলেনি'}",
    ]
    failed = [item for item in checks if "মেলেনি" in item]
    status = "সব চূড়ান্ত কাঠামোগত শর্ত পূরণ হয়েছে, কিন্তু অন্য দিকও একইভাবে বৈধ হওয়ায় দিকটি পরিষ্কার নয়।" if not failed else "যে কাঠামোগত শর্তগুলোতে সমস্যা হয়েছে: " + "; ".join(failed) + "."
    return "বহু-সময়সীমার স্কোরের বাধা বন্ধ আছে। বিস্তারিত যাচাই — " + " | ".join(checks) + "। " + status


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

    if buy_valid and not sell_valid:
        return Signal(
            "BUY",
            buy,
            sell,
            "বুলিশ এমএমসি: ৩০ মিনিট ও ১৫ মিনিটের বাজারের দিক ঊর্ধ্বমুখী এবং একমত। আগের প্রতিরোধের স্তর ভেঙে দাম আবার সেই স্তরে ফিরে এসে সেটিকে সমর্থন হিসেবে ধরে রেখেছে। ৫ মিনিটে কেনার প্রবেশের সংকেতও নিশ্চিত হয়েছে। বহু-সময়সীমার স্কোর এখন সিদ্ধান্তের বাধা নয়; স্কোর শুধু তথ্য হিসেবে দেখানো হচ্ছে।",
        )
    if sell_valid and not buy_valid:
        return Signal(
            "SELL",
            buy,
            sell,
            "বেয়ারিশ এমএমসি: ৩০ মিনিট ও ১৫ মিনিটের বাজারের দিক নিম্নমুখী এবং একমত। আগের সমর্থনের স্তর ভেঙে দাম আবার সেই স্তরে ফিরে এসে সেটিকে প্রতিরোধ হিসেবে ধরে রেখেছে। ৫ মিনিটে বিক্রির প্রবেশের সংকেতও নিশ্চিত হয়েছে। বহু-সময়সীমার স্কোর এখন সিদ্ধান্তের বাধা নয়; স্কোর শুধু তথ্য হিসেবে দেখানো হচ্ছে।",
        )
    if buy_valid and sell_valid:
        return Signal("NO_TRADE", buy, sell, "বহু-সময়সীমার স্কোর সিদ্ধান্তের বাধা নয়, কিন্তু কেনা ও বিক্রি—দুই দিকের কাঠামোগত শর্তই একসঙ্গে বৈধ হয়েছে; তাই দ্ব্যর্থক অবস্থায় ট্রেড দেওয়া হয়নি।")

    diagnostic = _diagnostic_reason(buy_profile, "buy") if buy >= sell else _diagnostic_reason(sell_profile, "sell")
    return Signal("NO_TRADE", buy, sell, diagnostic)


def generate_1m_signal(df: pd.DataFrame) -> Signal:
    """Pure 1-minute MMC entry using recent CLOSED candles.

    Existing MMC BOS/sweep/displacement logic is preserved. A strong rejection
    from a tested support/resistance level is added as an additional structure
    and trigger confirmation, so a bearish rejection at strong resistance can
    produce a SELL when the latest closed-candle trend is bearish.
    """
    if df is None or df.empty:
        return Signal("NO_TRADE", 0, 0, "১ মিনিটের বাজারের তথ্য পাওয়া যায়নি।")

    if len(df) < max(CONFIG.trend_ema, CONFIG.sweep_lookback + 1):
        return Signal("NO_TRADE", 0, 0, "১ মিনিটের প্রবণতা ও বাজারের কাঠামো যাচাই করার জন্য পর্যাপ্ত ক্যান্ডেল পাওয়া যায়নি।")

    work = df.copy()
    work["ema_fast"] = work["close"].ewm(span=CONFIG.fast_ema, adjust=False).mean()
    work["ema_trend"] = work["close"].ewm(span=CONFIG.trend_ema, adjust=False).mean()

    close = float(work["close"].iloc[-1])
    fast = float(work["ema_fast"].iloc[-1])
    trend = float(work["ema_trend"].iloc[-1])
    structure = market_structure(work, CONFIG.swing_lookback)
    sweep = liquidity_sweep(work, CONFIG.sweep_lookback)
    impulse = displacement(work)
    rejection = strong_level_rejection(work)

    # Scan the latest three CLOSED candles while preserving full history for
    # each structure/sweep/rejection calculation.
    recent_start = max(0, len(work) - 3)
    recent_indices = range(recent_start + 1, len(work) + 1)
    recent_bos = [market_structure(work.iloc[:i], CONFIG.swing_lookback) for i in recent_indices]
    recent_sweeps = [liquidity_sweep(work.iloc[:i], CONFIG.sweep_lookback) for i in recent_indices]
    recent_moves = [displacement(work.iloc[:i]) for i in recent_indices]
    recent_rejections = [strong_level_rejection(work.iloc[:i]) for i in recent_indices]

    bullish_bos_recent = "bullish_bos" in recent_bos
    bearish_bos_recent = "bearish_bos" in recent_bos
    buy_sweep_recent = "buy_side_rejection" in recent_sweeps
    sell_sweep_recent = "sell_side_rejection" in recent_sweeps
    bullish_move_recent = "bullish" in recent_moves
    bearish_move_recent = "bearish" in recent_moves
    buy_level_rejection_recent = "strong_support_rejection" in recent_rejections
    sell_level_rejection_recent = "strong_resistance_rejection" in recent_rejections

    buy_score = (
        int(close > trend)
        + int(fast > trend)
        + 2 * int(structure == "bullish_bos")
        + 2 * int(sweep == "buy_side_rejection")
        + int(impulse == "bullish")
        + 2 * int(rejection == "strong_support_rejection")
    )
    sell_score = (
        int(close < trend)
        + int(fast < trend)
        + 2 * int(structure == "bearish_bos")
        + 2 * int(sweep == "sell_side_rejection")
        + int(impulse == "bearish")
        + 2 * int(rejection == "strong_resistance_rejection")
    )

    # Trend remains strict on the latest closed candle.
    buy_trend = close > trend and fast > trend
    sell_trend = close < trend and fast < trend

    # Existing structure remains valid; strong support/resistance rejection is
    # an additional path rather than a replacement for BOS/sweep.
    buy_structure = bullish_bos_recent or buy_sweep_recent or buy_level_rejection_recent
    sell_structure = bearish_bos_recent or sell_sweep_recent or sell_level_rejection_recent

    # A strong level rejection is also a valid entry trigger.
    buy_trigger = buy_sweep_recent or bullish_move_recent or buy_level_rejection_recent
    sell_trigger = sell_sweep_recent or bearish_move_recent or sell_level_rejection_recent

    buy_valid = buy_trend and buy_structure and buy_trigger
    sell_valid = sell_trend and sell_structure and sell_trigger

    if buy_valid and not sell_valid:
        rejection_note = " শক্তিশালী support rejection-ও নিশ্চিত হয়েছে।" if buy_level_rejection_recent else ""
        return Signal("BUY", buy_score, sell_score, "১ মিনিটের এমএমসি: সর্বশেষ বন্ধ হওয়া ক্যান্ডেলে প্রবণতা ঊর্ধ্বমুখী এবং সাম্প্রতিক ৩টি বন্ধ ক্যান্ডেলের মধ্যে বাজারের কাঠামো/তারল্য সংগ্রহ/দ্রুত মূল্য-চলনের নিশ্চিতকরণ পাওয়া গেছে।" + rejection_note + " তাই পরবর্তী ১ মিনিটের ক্যান্ডেলকে BUY entry হিসেবে ধরা হয়েছে। ৩০, ১৫ ও ৫ মিনিট ব্যবহার করা হচ্ছে না; স্কোর তথ্য হিসেবে দেখানো হচ্ছে।")
    if sell_valid and not buy_valid:
        rejection_note = " শক্তিশালী resistance rejection পাওয়া গেছে—দাম resistance level পরীক্ষা/সুইপ করে নিচে close করেছে এবং bearish upper-wick rejection নিশ্চিত হয়েছে।" if sell_level_rejection_recent else ""
        return Signal("SELL", buy_score, sell_score, "১ মিনিটের এমএমসি: সর্বশেষ বন্ধ হওয়া ক্যান্ডেলে প্রবণতা নিম্নমুখী এবং সাম্প্রতিক ৩টি বন্ধ ক্যান্ডেলের মধ্যে বাজারের কাঠামো/তারল্য সংগ্রহ/দ্রুত মূল্য-চলনের নিশ্চিতকরণ পাওয়া গেছে।" + rejection_note + " তাই পরবর্তী ১ মিনিটের ক্যান্ডেলকে SELL entry হিসেবে ধরা হয়েছে। ৩০, ১৫ ও ৫ মিনিট ব্যবহার করা হচ্ছে না; স্কোর তথ্য হিসেবে দেখানো হচ্ছে।")
    if buy_valid and sell_valid:
        return Signal("NO_TRADE", buy_score, sell_score, "১ মিনিটের সাম্প্রতিক ৩টি বন্ধ ক্যান্ডেলে কেনা ও বিক্রি—দুই দিকের confirmation একসঙ্গে পাওয়া গেছে; তাই দ্ব্যর্থক অবস্থায় ট্রেড দেওয়া হয়নি।")

    return Signal("NO_TRADE", buy_score, sell_score, "১ মিনিটের এমএমসিতে সর্বশেষ বন্ধ হওয়া ক্যান্ডেলের trend এবং structure/trigger একদিকে যথেষ্ট নিশ্চিত নয়; তাই পরবর্তী ক্যান্ডেলে entry দেওয়া হয়নি।")
