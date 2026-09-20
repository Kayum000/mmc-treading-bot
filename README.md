# MMC Trading Bot

A market-signal engine for selected Real Forex and Quotex OTC 1-minute markets.

## Live signal pipeline

- **Real Market:** uses the selected Forex pair's browser WebSocket candle/quote data.
- **Quotex OTC:** uses the selected OTC market from the authenticated local Quotex collector.
- Both paths use the adaptive strategy in `strategy/adaptive_real.py`.
- The adaptive engine selects its logic from the detected market regime (for example TREND, BREAKOUT, RANGE, or HIGH_VOLATILITY).
- **Tick Pressure** remains available as a fallback when the adaptive engine has suitable fresh tick data; it is not the primary strategy.

## Entry timing

Signals are prepared for the upcoming 1-minute entry candle. The latest fully closed candle is used for analysis, and AUTO scheduling attempts to generate the signal a few seconds before the next minute boundary.

## Performance

Performance is based on the signal/entry candle's completed 1-minute candle:

- BUY + green/bullish candle close → লাভ
- BUY + red/bearish candle close → লস
- SELL + red/bearish candle close → লাভ
- SELL + green/bullish candle close → লস

## Strategy boundary

`strategy/otc_candle_pressure.py` is the OTC adapter around the adaptive strategy.

`strategy/tick_run_pressure.py` is retained as a tick-pressure fallback and is not the sole live entry strategy.

## Validation

Signal generation and performance tracking are software rules, not guarantees of trading profitability. Out-of-sample testing is required before treating any accuracy figure as reliable.

## Important

This repository generates trading signals only. It does not guarantee profitability and should not be treated as a validated trading system without appropriate testing and risk controls.
