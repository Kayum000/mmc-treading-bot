# EURUSD Tick-Run Signal Bot

A rule-based BUY / SELL / NO_TRADE signal engine using the new **Tick-Run Pressure** strategy. The live signal path no longer uses the previous MMC, MTF, sweep, MSS, support/resistance, ORB, candle-pattern, EMA, RSI, MACD, TickFlow, or Liquidity-Response strategies.

## Live market data

- **REAL_MARKET:** BiQuote historical tick endpoint for the selected Forex pair.
- The strategy uses the most recent 1,000 quote ticks.
- BiQuote's public FX tick feed exposes bid/ask/mid but does not expose consolidated bid/ask traded volume, so live mode does not fabricate volume data.

## New entry rule

1. Build the latest midpoint from bid/ask quotes.
2. Detect an **8-tick consecutive directional run**.
3. Reject signals when the current spread is too wide.
4. When bid/ask volume fields are available in research data, require strong same-side volume imbalance (0.60 threshold).
5. With the live BiQuote FX feed, use only observable quote direction because consolidated quote volume is unavailable.
6. Upward run → BUY; downward run → SELL; otherwise NO_TRADE.

## Strategy boundary

`strategy/tick_run_pressure.py` is the only live entry strategy.

`signals/get_signal.py` no longer imports or calls the previous strategy engines.

## Validation

The tick-run rule was discovered from the supplied tick dataset. A single-day result is not treated as proof of a robust 70% accuracy rate. Multi-day, unseen-data walk-forward validation is required before claiming 70%+ accuracy.

## Important

This repository generates signals only; it does not guarantee trading profitability and should not be treated as a validated live trading system until out-of-sample testing is completed.
