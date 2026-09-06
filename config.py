from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyConfig:
    # Pure MMC parameters. EMA values are intentionally not used by the strategy.
    swing_lookback: int = 3
    sweep_lookback: int = 10
    level_lookback: int = 20
    min_score: int = 0


TIMEFRAMES = ("30m", "15m", "5m")
CONFIG = StrategyConfig()
