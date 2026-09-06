from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyConfig:
    # Single-timeframe pure MMC parameters. No indicator or MTF settings.
    swing_lookback: int = 3
    sweep_lookback: int = 10
    level_lookback: int = 20
    min_score: int = 0


CONFIG = StrategyConfig()
