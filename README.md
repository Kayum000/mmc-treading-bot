# MMC Trading 

A single-strategy market-signal engine for selected Real Forex and Quotex OTC markets.

## Live signal pipeline

- **Real Forex (default):** `MARKET_DATA_PROVIDER=biquote` uses biquote public REST endpoints for live bid/ask quotes and completed 1-minute OHLC candles; no API key is required. The code rejects stale quotes/candles and never silently substitutes the Quotex collector feed. To use OANDA instead, set `MARKET_DATA_PROVIDER=oanda` and configure `OANDA_ACCESS_TOKEN`, `OANDA_ACCOUNT_ID`, and `OANDA_ENVIRONMENT=practice` (or `live`).
- **Quotex OTC:** signals use closed candles from the selected OTC market collected from the user's authenticated Quotex browser session. OTC is not substituted with Forex prices.
- The provider quote is a live bid/ask midpoint; the strategy analyzes only completed provider candles. biquote/OANDA prices may differ from Quotex prices, and this integration does not place trades.
- Real Forex and Quotex OTC signals route through `generate_quotex_price_action_signal()` from `strategy/quotex_price_action.py` via `signals/get_signal.py`. biquote is a separate Forex feed and does not claim its prices exactly match Quotex's feed or OTC prices.
- The live strategy analyzes closed 1-minute candles and derives completed 5-minute and 15-minute candles for market-structure context. It checks confirmed swing highs/lows (HH/HL or LH/LL), support/resistance, liquidity sweeps/reclaims, break of structure, and supply/demand rejection. It does not use indicator votes to decide direction.
- BUY/SELL requires aligned directional structure on both 5m and 15m plus a matching 1m price-action setup. Neutral/conflicting context, weak candles, insufficient history, or missing confluence returns HOLD (no signal).
- The configured expiry is 5 minutes from the scheduled entry-minute boundary. Performance scoring compares the entry-minute open with the close of the 1-minute candle ending at entry + 5 minutes. This is an OHLC-based historical fill proxy; spread, slippage, broker execution, and payout are not modeled. The bot does not place trades or guarantee profitability.
- `strategy/adaptive_real.py` contains a separate regime-adaptive engine (TREND, BREAKOUT, RANGE, and HIGH_VOLATILITY), and `strategy/otc_candle_pressure.py` wraps that engine. **These modules are not currently on the live signal path described above.** Do not assume the live endpoints are using the regime-adaptive selector unless `signals/get_signal.py` is changed to call it.
- The hybrid strategy accepts a `ticks` argument, but its current decision logic is candle/indicator based; the live signal path should not be described as using a tick-pressure fallback.

## Entry timing

Signals are prepared for the upcoming 1-minute entry candle. The latest fully closed candle is used for analysis, and AUTO scheduling attempts to generate the signal a few seconds before the next minute boundary. Actionable signals expose `expiry_minutes=5` and an expiry timestamp five minutes after the scheduled entry boundary.

## Performance

Performance is scored after the five-minute expiry using the entry-minute open as a historical fill proxy and the close of the 1-minute candle ending at entry + 5 minutes:

- BUY + expiry close above entry-minute open → লাভ
- BUY + expiry close below entry-minute open → লস
- SELL + expiry close below entry-minute open → লাভ
- SELL + expiry close above entry-minute open → লস
- Equal entry and expiry prices → DOJI

This is an OHLC-based outcome label, not an account-level profit calculation. Spread, slippage, execution timing, broker quote differences, and payout are not modeled.

## Strategy boundary

- `signals/get_signal.py` is the live routing layer for Real and Quotex OTC requests. Real Forex uses biquote by default (or OANDA when explicitly configured); OTC continues to use the authenticated Quotex collector.
- `strategy/quotex_price_action.py` is the strict Price Action engine used by both live Quotex modes in this branch.
- `strategy/mmc_hybrid.py` remains in the repository for comparison/rollback, but is no longer called by the live signal routing in this branch.
- `strategy/adaptive_real.py` and `strategy/otc_candle_pressure.py` remain separate modules and are not used by the live routing layer.
- `strategy/tick_run_pressure.py` is a separate module; it is not the live entry strategy in the current signal path.

## Validation

Signal generation and performance tracking are software rules, not guarantees of trading profitability. Run syntax checks, integration tests, and out-of-sample backtests before treating any accuracy figure as reliable.

## Important

This repository generates trading signals only. It does not guarantee profitability and should not be treated as a validated trading system without appropriate testing and risk controls.
