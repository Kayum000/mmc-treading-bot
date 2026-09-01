# MMC Multi-Timeframe Signal Bot

A rule-based educational signal engine for BUY / SELL / NO_TRADE decisions using a simplified MMC-style market-structure model and multi-timeframe confirmation.

## Timeframes

- **15m:** primary trend/structure bias (highest weight)
- **5m:** setup confirmation
- **1m:** entry confirmation

## Logic in v1

1. EMA trend alignment (20/50)
2. Basic market-structure break (BOS)
3. Liquidity sweep and reclaim
4. Candle displacement
5. Weighted multi-timeframe score
6. BUY/SELL only when the minimum score is met and the two sides are not tied

The current implementation is intentionally conservative: it produces signals only and **does not place trades** or store broker credentials/tokens.

## Run

```bash
pip install -r requirements.txt
python main.py --tf15 data/15m.csv --tf5 data/5m.csv --tf1 data/1m.csv
```

CSV files need these OHLC columns:

`open, high, low, close`

> This is a research/prototyping implementation. Binary-options trading is high risk; signals are not guaranteed to be profitable.
