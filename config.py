from dataclasses import dataclass

@dataclass(frozen=True)
class StrategyConfig:
    trend_ema: int = 50
    fast_ema: int = 20
    swing_lookback: int = 3
    sweep_lookback: int = 10
    min_score: int = 6

TIMEFRAMES = ("15m", "5m", "1m")
CONFIG = StrategyConfig()
