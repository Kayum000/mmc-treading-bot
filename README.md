# MMC Clean 1-Minute Signal Bot

A rule-based signal engine for BUY / SELL / NO_TRADE decisions using one canonical clean MMC strategy on **completed 1-minute candles only**.

## Market modes

- **REAL_MARKET:** live Forex candles from the configured Twelve Data feed.
- **CRYPTO:** public Binance 1-minute candle data.

These modes generate signals only. They do **not** submit orders.

## Entry rule

The strategy has one decision path:

1. Build confirmed support/resistance from prior closed 1m price action.
2. Require a **strong** level with repeated touches.
3. Require rejection/reclaim at that level.
4. Require same-direction MMC confirmation from liquidity sweep and/or displacement.
5. **Strong support + bullish confirmation → BUY**.
6. **Strong resistance + bearish confirmation → SELL**.
7. A level touch by itself never creates a signal.
8. The running candle is never used as the entry candle; a confirmed signal is always for the **next 1-minute candle**.

There is **no multi-timeframe strategy** and no EMA/RSI/MACD decision layer.

## Loss protection

A confirmed BUY/SELL is stored in persistent PostgreSQL performance storage for 24 hours.

After exactly **one LOSS**, that market/pair is locked and signals remain OFF. A NO_TRADE observation does **not** clear the lock. The lock is cleared only when a later check has both:

- a **new strong support/resistance level**, materially different from the losing setup's stored level; and
- a **fresh same-direction MMC confirmation**.

Only then can a new BUY/SELL signal be issued.

## Web behavior

- GET SIGNAL analyzes only the selected market.
- AUTO SIGNAL remains available and also analyzes only the selected market.
- No simultaneous 20-market strategy analysis is performed.
- The UI keeps the next-candle entry time visible.
- Performance shows confirmed BUY/SELL results for the last 24 hours; WAIT/NO_TRADE is not counted as a trade result.

## Canonical strategy location

All MMC decision logic lives in `strategy/mmc.py`.

`strategy/reentry_guard.py` is only a persistent one-entry-per-level protection layer; it reuses the canonical MMC level calculation.

## Historical backtest

`backtest/mmc_backtest.py` uses the same canonical 1m MMC strategy on historical 1-minute OHLC data. It does not resample into higher timeframes and does not call the live API.

Example:

```bash
python -m backtest.mmc_backtest data/1m.csv --out backtest_results
```

Accuracy is calculated from WIN/LOSS outcomes; DRAW is reported separately. Historical results are descriptive only and do not guarantee future profitability.

## Data boundary

The live network/data modules remain separate from the strategy engine. The strategy itself consumes only the selected market's completed 1m OHLC data.

> Research/prototyping only. Trading and binary-options trading are high risk; signals are not guaranteed to be profitable.
