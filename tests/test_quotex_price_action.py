import unittest

import pandas as pd

from strategy.quotex_price_action import generate_quotex_price_action_signal


def make_candles(count=100, flat=False):
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=count, freq="min")
    rows = []
    price = 100.0
    for i, stamp in enumerate(timestamps):
        if flat:
            op = close = price
            high = price + 0.01
            low = price - 0.01
        else:
            drift = 0.03 if (i % 7) not in (4, 5) else -0.01
            op = price
            close = price + drift
            high = max(op, close) + 0.02
            low = min(op, close) - 0.02
            price = close
        rows.append({
            "timestamp": stamp, "open": op, "high": high, "low": low, "close": close,
        })
    return pd.DataFrame(rows)


class QuotexPriceActionTests(unittest.TestCase):
    def test_insufficient_history_returns_hold(self):
        result = generate_quotex_price_action_signal(make_candles(25))
        self.assertEqual(result.action, "HOLD")
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.mmc_analysis["candle_count"], 25)

    def test_flat_market_returns_hold_instead_of_forced_direction(self):
        result = generate_quotex_price_action_signal(make_candles(120, flat=True))
        self.assertEqual(result.action, "HOLD")
        self.assertEqual(result.regime, "NO_TRADE")

    def test_missing_required_columns_returns_hold(self):
        result = generate_quotex_price_action_signal(pd.DataFrame({"close": [1, 2, 3]}))
        self.assertEqual(result.action, "HOLD")
        self.assertEqual(result.regime, "NO_TRADE")

    def test_confidence_is_not_described_as_win_probability(self):
        result = generate_quotex_price_action_signal(make_candles(100))
        self.assertEqual(
            result.mmc_analysis["confidence_basis"],
            "rule_strength_not_win_probability",
        )
        if result.action == "HOLD":
            self.assertEqual(result.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
