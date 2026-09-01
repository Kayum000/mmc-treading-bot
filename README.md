# MMC Multi-Timeframe Signal Bot

A rule-based signal engine for BUY / SELL / NO_TRADE decisions using a simplified MMC-style market-structure model and multi-timeframe confirmation.

## Market modes

- **REAL_MARKET:** normalized candles from a user-authorized live feed (including a broker-compatible feed where permitted).
- **CRYPTO:** public Binance candle data. No Binance API key is required for public market data.

These modes generate signals only. They do **not** submit orders.

## Timeframes

- **15m:** primary trend/structure bias (highest weight)
- **5m:** setup confirmation
- **1m:** entry confirmation

## Logic

1. EMA trend alignment (20/50)
2. Market-structure break (BOS)
3. Liquidity sweep and rejection
4. Candle displacement
5. Weighted multi-timeframe score
6. BUY/SELL only when the minimum score is met and the two sides are not tied

## Data boundary

`data/market_modes.py` selects `REAL_MARKET` or `CRYPTO`.

`data/quotex_adapter.py` accepts normalized candles from an authorized source without handling passwords/tokens or placing orders.

`data/binance_adapter.py` normalizes public Binance klines for 1m, 5m and 15m analysis.

The live network transport is intentionally kept separate from the strategy engine so a data source can be tested without enabling trade execution.

> Research/prototyping only. Market and binary-options trading are high risk; signals are not guaranteed to be profitable.
