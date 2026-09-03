from dataclasses import dataclass

@dataclass(frozen=True)
class StrategyConfig:
    trend_ema: int = 50
    fast_ema: int = 20
    swing_lookback: int = 3
    sweep_lookback: int = 10
    # Higher threshold because the MTF score now requires stronger confirmation.
    min_score: int = 12

TIMEFRAMES = ("30m", "15m", "5m")
CONFIG = StrategyConfig()
