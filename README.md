# MMC Trading Bot

A market-signal engine for selected Real Forex and Quotex OTC 1-minute markets.

## Live signal pipeline

- **Real Forex:** signals use the selected pair's fresh Quotex browser WebSocket data. If the collector is disconnected or data is older than 60 seconds, the app reports that fresh Quotex data is unavailable; it does not substitute another provider's prices.
- **Quotex OTC:** signals use closed candles from the selected OTC market collected from the user's authenticated Quotex browser session. OTC is not substituted with Forex prices.
- Both live modes currently call `generate_hybrid_signal()` from `strategy/mmc_hybrid.py` via `signals/get_signal.py`.
- The live hybrid engine evaluates 22 OHLC-based market-structure/price-action heuristics and checks 1-minute indicators plus available 5-minute and 15-minute context. It requires at least 60 closed 1-minute candles and uses a conservative vote threshold before returning BUY or SELL; otherwise it returns HOLD.
- `strategy/adaptive_real.py` contains a separate regime-adaptive engine (TREND, BREAKOUT, RANGE, and HIGH_VOLATILITY), and `strategy/otc_candle_pressure.py` wraps that engine. **These modules are not currently on the live signal path described above.** Do not assume the live endpoints are using the regime-adaptive selector unless `signals/get_signal.py` is changed to call it.
- The hybrid strategy accepts a `ticks` argument, but its current decision logic is candle/indicator based; the live signal path should not be described as using a tick-pressure fallback.

## Entry timing

Signals are prepared for the upcoming 1-minute entry candle. The latest fully closed candle is used for analysis, and AUTO scheduling attempts to generate the signal a few seconds before the next minute boundary.

## Performance

Performance is based on the signal/entry candle's completed 1-minute candle:

- BUY + green/bullish candle close → লাভ
- BUY + red/bearish candle close → লস
- SELL + red/bearish candle close → লাভ
- SELL + green/bullish candle close → লস

A candle-colour result is a simple outcome label, not a full account-level profit calculation; payout, spread, execution timing, and other trading costs may affect actual results.

## Strategy boundary

- `signals/get_signal.py` is the live routing layer for Real and Quotex OTC requests.
- `strategy/mmc_hybrid.py` is the hybrid engine currently used by both live modes.
- `strategy/adaptive_real.py` and `strategy/otc_candle_pressure.py` are separate adaptive-strategy modules, not currently used by the live routing layer.
- `strategy/tick_run_pressure.py` is a separate module; it is not the live entry strategy in the current signal path.

## Validation

Signal generation and performance tracking are software rules, not guarantees of trading profitability. Run syntax checks, integration tests, and out-of-sample backtests before treating any accuracy figure as reliable.

## Important

This repository generates trading signals only. It does not guarantee profitability and should not be treated as a validated trading system without appropriate testing and risk controls.
