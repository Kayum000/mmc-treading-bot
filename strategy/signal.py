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


def _recent_momentum_ok(work: pd.DataFrame, side: str) -> bool:
    """Reject reversal entries when short-term momentum is still against them.

    A support/resistance wick alone can appear during a continuing impulse.
    We allow a normal one/two-candle pullback, but block entries when the last
    four closes show persistent directional pressure and the fast EMA is also
    sloping in that same adverse direction.
    """
    if len(work) < 6:
        return True

    closes = work["close"].astype(float).iloc[-4:]
    fast = work["ema_fast"].astype(float)
    fast_slope = float(fast.iloc[-1] - fast.iloc[-4])
    down_steps = int((closes.diff().iloc[1:] < 0).sum())
    up_steps = int((closes.diff().iloc[1:] > 0).sum())

    if side == "buy":
        return not (down_steps >= 3 and fast_slope < 0)
    return not (up_steps >= 3 and fast_slope > 0)


def generate_1m_signal(df: pd.DataFrame) -> Signal:
    """Pure 1-minute MMC entry using recent CLOSED candles.

    A trade now requires a strong support/resistance rejection on the latest
    closed candle plus at least two independent confirmations from the recent
    setup: liquidity sweep, displacement, or BOS. The latest closed-candle
    trend must also agree. This deliberately favors fewer, stronger entries.
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
    latest_open = float(work["open"].iloc[-1]) if "open" in work.columns else close
    structure = market_structure(work, CONFIG.swing_lookback)
    sweep = liquidity_sweep(work, CONFIG.sweep_lookback)
    impulse = displacement(work)
    rejection = strong_level_rejection(work)

    # Scan the latest three CLOSED candles while preserving full history for
    # each structure/sweep calculation. Rejection itself must be on the latest
    # closed candle because the entry is for the immediately next candle.
    recent_start = max(0, len(work) - 3)
    recent_indices = range(recent_start + 1, len(work) + 1)
    recent_bos = [market_structure(work.iloc[:i], CONFIG.swing_lookback) for i in recent_indices]
    recent_sweeps = [liquidity_sweep(work.iloc[:i], CONFIG.sweep_lookback) for i in recent_indices]
    recent_moves = [displacement(work.iloc[:i]) for i in recent_indices]

    bullish_bos_recent = "bullish_bos" in recent_bos
    bearish_bos_recent = "bearish_bos" in recent_bos
    buy_sweep_recent = "buy_side_rejection" in recent_sweeps
    sell_sweep_recent = "sell_side_rejection" in recent_sweeps
    bullish_move_recent = "bullish" in recent_moves
    bearish_move_recent = "bearish" in recent_moves
    buy_level_rejection_recent = rejection == "strong_support_rejection"
    sell_level_rejection_recent = rejection == "strong_resistance_rejection"

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

    # Strong level rejection is mandatory for every 1m entry. In addition,
    # require the latest rejection candle body to point in the trade direction.
    buy_level = buy_level_rejection_recent and close > latest_open
    sell_level = sell_level_rejection_recent and close < latest_open

    # Require at least TWO confirmations among BOS, liquidity sweep and
    # displacement within the recent closed-candle setup. strong_level_rejection
    # itself already requires sweep OR displacement on the latest candle, so
    # this adds a second independent confirmation instead of allowing a single
    # event to create an entry.
    buy_confirmation_count = int(buy_sweep_recent) + int(bullish_move_recent) + int(bullish_bos_recent)
    sell_confirmation_count = int(sell_sweep_recent) + int(bearish_move_recent) + int(bearish_bos_recent)

    # Anti-chase filter: a wick at support/resistance is not enough if the
    # short-term impulse is still pressing strongly in the opposite direction.
    buy_momentum_ok = _recent_momentum_ok(work, "buy")
    sell_momentum_ok = _recent_momentum_ok(work, "sell")

    buy_valid = buy_trend and buy_level and buy_confirmation_count >= 2 and buy_momentum_ok
    sell_valid = sell_trend and sell_level and sell_confirmation_count >= 2 and sell_momentum_ok

    if buy_valid and not sell_valid:
        return Signal(
            "BUY",
            buy_score,
            sell_score,
            "১ মিনিটের কঠোর এমএমসি: সর্বশেষ বন্ধ হওয়া ক্যান্ডেলে bullish support rejection হয়েছে, অন্তত দুটি bullish confirmation মিলেছে এবং short-term momentum BUY-এর বিপরীতে শক্তিশালী নয়। তাই পরবর্তী ১ মিনিটের ক্যান্ডেলকে BUY entry হিসেবে ধরা হয়েছে।",
        )
    if sell_valid and not buy_valid:
        return Signal(
            "SELL",
            buy_score,
            sell_score,
            "১ মিনিটের কঠোর এমএমসি: সর্বশেষ বন্ধ হওয়া ক্যান্ডেলে bearish resistance rejection হয়েছে, অন্তত দুটি bearish confirmation মিলেছে এবং short-term momentum SELL-এর বিপরীতে শক্তিশালী নয়। তাই পরবর্তী ১ মিনিটের ক্যান্ডেলকে SELL entry হিসেবে ধরা হয়েছে।",
        )
    if buy_valid and sell_valid:
        return Signal("NO_TRADE", buy_score, sell_score, "১ মিনিটের শক্তিশালী level, confirmation ও momentum filter—দুই দিকেই একসঙ্গে বৈধ হয়েছে; তাই দ্ব্যর্থক অবস্থায় entry দেওয়া হয়নি।")

    return Signal(
        "NO_TRADE",
        buy_score,
        sell_score,
        "১ মিনিটের কঠোর MMC filter পূরণ হয়নি: strong support/resistance level, latest trend, candle direction, অন্তত দুটি একই-direction confirmation এবং বিপরীত short-term momentum filter—সব একসঙ্গে না পাওয়া পর্যন্ত entry দেওয়া হবে না।",
    )
