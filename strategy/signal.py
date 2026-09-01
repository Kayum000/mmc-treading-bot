from dataclasses import dataclass
import pandas as pd

from config import CONFIG
from strategy.multi_timeframe import multi_timeframe_score


@dataclass(frozen=True)
class Signal:
    action: str
    buy_score: int
    sell_score: int
    reason: str


def generate_signal(frames: dict[str, pd.DataFrame]) -> Signal:
    buy = multi_timeframe_score(frames, "buy")
    sell = multi_timeframe_score(frames, "sell")

    if buy >= CONFIG.min_score and buy > sell:
        return Signal("BUY", buy, sell, "Bullish multi-timeframe MMC confirmation")
    if sell >= CONFIG.min_score and sell > buy:
        return Signal("SELL", buy, sell, "Bearish multi-timeframe MMC confirmation")
    return Signal("NO_TRADE", buy, sell, "Insufficient or conflicting confirmation")
