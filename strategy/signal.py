from dataclasses import dataclass

import pandas as pd

from config import CONFIG
from strategy.mmc import (
    displacement,
    final_confirmation,
    liquidity_sweep,
    market_structure,
    strong_level_rejection,
)


@dataclass(frozen=True)
class Signal:
    action: str
    buy_score: int
    sell_score: int
    reason: str


def generate_signal(df: pd.DataFrame) -> Signal:
    """Single-timeframe, pure-MMC decision path for the latest closed candle.

    Chain: strong support/resistance -> rejection -> sweep/displacement/BOS
    confirmation -> BUY/SELL for the next 1-minute candle. There is no MTF
    layer and no EMA/RSI/MACD dependency.
    """
    minimum = max(CONFIG.sweep_lookback + 1, CONFIG.level_lookback + 5, 23)
    if df is None or df.empty:
        return Signal("NO_TRADE", 0, 0, "বাজারের ১ মিনিটের তথ্য পাওয়া যায়নি।")
    if len(df) < minimum:
        return Signal("NO_TRADE", 0, 0, "পরিষ্কার MMC যাচাইয়ের জন্য পর্যাপ্ত বন্ধ ১ মিনিটের ক্যান্ডেল নেই।")

    structure = market_structure(df, CONFIG.swing_lookback)
    sweep = liquidity_sweep(df, CONFIG.sweep_lookback)
    impulse = displacement(df)
    rejection = strong_level_rejection(df, CONFIG.level_lookback)

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

    buy_confirmation = (
        rejection == "strong_support_rejection"
        and final_confirmation(df, "buy", CONFIG.level_lookback)
        and (
            (sweep == "buy_side_rejection" and impulse == "bullish")
            or structure == "bullish_bos"
        )
    )
    sell_confirmation = (
        rejection == "strong_resistance_rejection"
        and final_confirmation(df, "sell", CONFIG.level_lookback)
        and (
            (sweep == "sell_side_rejection" and impulse == "bearish")
            or structure == "bearish_bos"
        )
    )

    if buy_confirmation and not sell_confirmation:
        return Signal(
            "BUY",
            buy_score,
            sell_score,
            "ক্লিন MMC BUY: শক্ত support level-এ rejection এবং bullish confirmation পাওয়া গেছে। পরবর্তী 1m candle-এ entry।",
        )
    if sell_confirmation and not buy_confirmation:
        return Signal(
            "SELL",
            buy_score,
            sell_score,
            "ক্লিন MMC SELL: শক্ত resistance level-এ rejection এবং bearish confirmation পাওয়া গেছে। পরবর্তী 1m candle-এ entry।",
        )
    if buy_confirmation and sell_confirmation:
        return Signal("NO_TRADE", buy_score, sell_score, "একই candle-এ দুই দিকের MMC confirmation এসেছে; তাই entry নেই।")

    if rejection == "strong_support_rejection":
        return Signal("NO_TRADE", buy_score, sell_score, "Support rejection হয়েছে, কিন্তু সম্পূর্ণ bullish confirmation হয়নি; BUY বন্ধ।")
    if rejection == "strong_resistance_rejection":
        return Signal("NO_TRADE", buy_score, sell_score, "Resistance rejection হয়েছে, কিন্তু সম্পূর্ণ bearish confirmation হয়নি; SELL বন্ধ।")
    return Signal("NO_TRADE", buy_score, sell_score, "শক্ত MMC support/resistance rejection এবং confirmation একসঙ্গে তৈরি হয়নি; তাই signal নেই।")


# Backward-compatible helper for callers that still pass a 1m dataframe.
def generate_1m_signal(df: pd.DataFrame) -> Signal:
    return generate_signal(df)
