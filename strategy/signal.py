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
        f"ভাঙা স্তরের পুনঃপরীক্ষা ও নতুন ভূমিকা: {'ঠিক আছে' if profile['role_reversal_confirmation'] else 'মেলেনি'}",
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

    # Scores are still calculated and returned for visibility/monitoring,
    # but they no longer decide whether a structurally valid setup is traded.
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
    """Pure 1-minute MMC entry strategy; higher timeframes are not required."""
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

    buy_score = int(close > trend) + int(fast > trend) + 2 * int(structure == "bullish_bos") + 2 * int(sweep == "buy_side_rejection") + int(impulse == "bullish")
    sell_score = int(close < trend) + int(fast < trend) + 2 * int(structure == "bearish_bos") + 2 * int(sweep == "sell_side_rejection") + int(impulse == "bearish")

    buy_trend = close > trend and fast > trend
    sell_trend = close < trend and fast < trend
    buy_structure = structure == "bullish_bos" or sweep == "buy_side_rejection"
    sell_structure = structure == "bearish_bos" or sweep == "sell_side_rejection"
    buy_trigger = sweep == "buy_side_rejection" or impulse == "bullish"
    sell_trigger = sweep == "sell_side_rejection" or impulse == "bearish"

    buy_valid = buy_trend and buy_structure and buy_trigger
    sell_valid = sell_trend and sell_structure and sell_trigger

    if buy_valid and not sell_valid:
        return Signal("BUY", buy_score, sell_score, "১ মিনিটের এমএমসি: স্বল্পমেয়াদি প্রবণতা ঊর্ধ্বমুখী, বাজারের কাঠামো বা তারল্য সংগ্রহের নিশ্চিতকরণও ঊর্ধ্বমুখী, এবং সর্বশেষ সম্পূর্ণ বন্ধ হওয়া ১ মিনিটের ক্যান্ডেলে কেনার প্রবেশ-সংকেত নিশ্চিত হয়েছে। ৩০, ১৫ ও ৫ মিনিটের তথ্য এখানে ব্যবহার করা হচ্ছে না; স্কোর শুধু তথ্য হিসেবে দেখানো হচ্ছে।")
    if sell_valid and not buy_valid:
        return Signal("SELL", buy_score, sell_score, "১ মিনিটের এমএমসি: স্বল্পমেয়াদি প্রবণতা নিম্নমুখী, বাজারের কাঠামো বা তারল্য সংগ্রহের নিশ্চিতকরণও নিম্নমুখী, এবং সর্বশেষ সম্পূর্ণ বন্ধ হওয়া ১ মিনিটের ক্যান্ডেলে বিক্রির প্রবেশ-সংকেত নিশ্চিত হয়েছে। ৩০, ১৫ ও ৫ মিনিটের তথ্য এখানে ব্যবহার করা হচ্ছে না; স্কোর শুধু তথ্য হিসেবে দেখানো হচ্ছে।")
    if buy_valid and sell_valid:
        return Signal("NO_TRADE", buy_score, sell_score, "১ মিনিটে কেনা ও বিক্রি—দুই দিকের শর্ত একসঙ্গে বৈধ হয়েছে; তাই দিক পরিষ্কার না হওয়ায় কোনো ট্রেড দেওয়া হয়নি।")

    failed = []
    if not (buy_trend or sell_trend):
        failed.append("স্বল্পমেয়াদি প্রবণতা পরিষ্কার নয়")
    if not (buy_structure or sell_structure):
        failed.append("বাজারের কাঠামো বা তারল্য সংগ্রহের নিশ্চিতকরণ নেই")
    if not (buy_trigger or sell_trigger):
        failed.append("দাম দ্রুত সরে যাওয়া বা প্রত্যাখ্যানের প্রবেশ-সংকেত নেই")
    return Signal("NO_TRADE", buy_score, sell_score, "১ মিনিটের এমএমসিতে এখনো বৈধ সেটআপ নেই: " + "; ".join(failed) + ".")


def confirm_1m_entry(signal: Signal, df_1m: pd.DataFrame) -> Signal:
    """Use the latest closed 1m candle as the final entry trigger for MTF mode."""
    if signal.action not in {"BUY", "SELL"}:
        return signal
    if df_1m is None or df_1m.empty:
        return Signal(signal.action, signal.buy_score, signal.sell_score, signal.reason + " ১ মিনিটের প্রবেশ যাচাইয়ের জন্য তথ্য পাওয়া যায়নি; ট্রেড বাতিল করা হয়েছে।")

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
            signal.reason + " সর্বশেষ সম্পূর্ণ বন্ধ হওয়া ১ মিনিটের ক্যান্ডেলেও একই দিকের প্রবেশ-সংকেত নিশ্চিত হয়েছে; পরবর্তী ১ মিনিটের ক্যান্ডেলে প্রবেশের জন্য প্রস্তুত।",
        )

    return Signal(
        "NO_TRADE",
        signal.buy_score,
        signal.sell_score,
        signal.reason + " সর্বশেষ সম্পূর্ণ বন্ধ হওয়া ১ মিনিটের ক্যান্ডেলে একই দিকের বাজার ভাঙন, তারল্য সংগ্রহ ও পুনরুদ্ধার, অথবা দ্রুত মূল্য-চলন নিশ্চিত হয়নি; তাই পরবর্তী ১ মিনিটের ক্যান্ডেলে প্রবেশ দেওয়া হয়নি।",
    )
