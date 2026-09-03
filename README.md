# MMC Multi-Timeframe Signal Bot

A rule-based signal engine for BUY / SELL / NO_TRADE decisions using a simplified MMC-style market-structure model and multi-timeframe confirmation.

## Market modes

- **REAL_MARKET:** normalized candles from a user-authorized live feed (including a broker-compatible feed where permitted).
- **CRYPTO:** public Binance candle data. No Binance API key is required for public market data.

These modes generate signals only. They do **not** submit orders.

## Timeframes

- **30m:** higher-timeframe trend/structure confirmation (highest weight)
- **15m:** higher-timeframe confirmation
- **5m:** setup confirmation
- **1m:** final entry confirmation

The live entry architecture is **30m → 15m → 5m setup → 1m final entry**. The 1m confirmation is not mixed into the MTF score.

## Logic

1. EMA trend alignment (20/50)
2. Market-structure break (BOS)
3. Liquidity sweep and rejection
4. Candle displacement
5. Breakout/retest role reversal
6. Weighted multi-timeframe score (30m=3, 15m=2, 5m=1)
7. Final 1m entry confirmation
8. BUY/SELL only when all mandatory confirmation gates are satisfied

## Weekly news + sentiment

The web panel shows the week's scheduled economic events across all supported pairs and raises a **5-minute pre-news alert**. Scheduled-event timing comes from the weekly economic calendar. When `ALPHA_VANTAGE_API_KEY` is configured, the bot also fetches Alpha Vantage `NEWS_SENTIMENT` data and adds recent published-news sentiment as context.

The Alpha Vantage news request is cached for 5 minutes and is made as one broad request per cache window rather than once per market, so the 20 Forex / 10 Crypto pair list does not multiply news API calls.

Set the key in the server environment (for example, Render Environment Variables):

```text
ALPHA_VANTAGE_API_KEY=your_key_here
```

If the key is not configured or the news provider is unavailable, the scheduled calendar remains available and the sentiment layer is simply omitted.

## Historical accuracy backtest

`backtest/mmc_backtest.py` measures the same signal logic on historical **1-minute OHLC** data without calling the live API. It resamples the 1m candles into 5m/15m/30m frames, evaluates signals only from data available at that time, confirms the 1m entry, and evaluates the next 1-minute candle as the outcome.

Example:

```bash
python -m backtest.mmc_backtest data/1m.csv --out backtest_results
```

The report creates:

- `signals.csv` — every confirmed historical signal and WIN/LOSS/DRAW outcome
- `score_report.csv` — accuracy grouped by **12–14, 15–17, 18–21, 22+** score ranges
- `direction_report.csv` — BUY vs SELL results

Accuracy is calculated as `wins / (wins + losses)`; DRAWs are reported separately. The report is for historical measurement only and is not a guarantee of future profitability.

## Data boundary

`data/market_modes.py` selects `REAL_MARKET` or `CRYPTO`.

`data/quotex_adapter.py` accepts normalized candles from an authorized source without handling passwords/tokens or placing orders.

`data/binance_adapter.py` normalizes public Binance klines for 1m, 5m and 15m analysis.

The live network transport is intentionally kept separate from the strategy engine so a data source can be tested without enabling trade execution.

> Research/prototyping only. Market and binary-options trading are high risk; signals are not guaranteed to be profitable.
