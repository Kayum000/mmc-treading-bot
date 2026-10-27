# MMC Trading 

A market-signal engine for selected Real Forex and Quotex OTC 1-minute markets.

## Live signal pipeline

- **Real Forex:** when `TWELVEDATA_API_KEY` is configured on the server, signals use Twelve Data's 1-minute Forex OHLC API for standard currency pairs (for example, `EUR/USD` or `EURUSD`). Only completed candles are analyzed; stale data, API errors, and rate limits return an error instead of fabricated or alternate-provider prices. If the key is absent, the existing Quotex browser WebSocket collector path remains in use.
- **Quotex OTC:** signals use closed candles from the selected OTC market collected from the user's authenticated Quotex browser session. OTC is not substituted with Forex prices.
- Real Forex and Quotex OTC signals route through `generate_quotex_price_action_signal()` from `strategy/quotex_price_action.py` via `signals/get_signal.py`. The Twelve Data branch uses provider OHLC candles and does not claim those prices exactly match Quotex's feed or OTC prices.
- The price-action engine requires at least 60 valid closed 1-minute candles, a clear 5-minute EMA9/EMA21 trend, and a matching 1-minute support/resistance rejection or breakout/retest confirmation. Weak candles, neutral trend, insufficient data, conflicting setups, or missing confluence return HOLD rather than forcing BUY/SELL.
- The engine includes a suggested invalidation level and demo-only expiry guidance (compare 60s and 120s); it does not place trades, set stake sizes, validate profitability, or guarantee a winning outcome.
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

- `signals/get_signal.py` is the live routing layer for Real and Quotex OTC requests. Real Forex uses Twelve Data when `TWELVEDATA_API_KEY` is set; OTC continues to use the authenticated Quotex collector.
- `strategy/quotex_price_action.py` is the strict Price Action engine used by both live Quotex modes in this branch.
- `strategy/mmc_hybrid.py` remains in the repository for comparison/rollback, but is no longer called by the live signal routing in this branch.
- `strategy/adaptive_real.py` and `strategy/otc_candle_pressure.py` remain separate modules and are not used by the live routing layer.
- `strategy/tick_run_pressure.py` is a separate module; it is not the live entry strategy in the current signal path.

## Validation

Signal generation and performance tracking are software rules, not guarantees of trading profitability. Run syntax checks, integration tests, and out-of-sample backtests before treating any accuracy figure as reliable.

## Important

This repository generates trading signals only. It does not guarantee profitability and should not be treated as a validated trading system without appropriate testing and risk controls.
