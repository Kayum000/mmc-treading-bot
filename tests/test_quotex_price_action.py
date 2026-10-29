import unittest
import pandas as pd

from strategy.quotex_price_action import generate_quotex_price_action_signal, _resample_closed, _structure_bias


def make_candles(count=240, flat=False):
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=count, freq="min")
    rows, price = [], 100.0
    for i, stamp in enumerate(timestamps):
        drift = 0.0 if flat else (0.03 if (i % 7) not in (4, 5) else -0.01)
        op = price
        close = price + drift
        high = max(op, close) + (0.01 if flat else 0.02)
        low = min(op, close) - (0.01 if flat else 0.02)
        rows.append({"timestamp": stamp, "open": op, "high": high, "low": low, "close": close})
        price = close
    return pd.DataFrame(rows)


class ForexStructureStrategyTests(unittest.TestCase):
    def test_insufficient_history_returns_hold(self):
        result = generate_quotex_price_action_signal(make_candles(90))
        self.assertEqual(result.action, "HOLD")
        self.assertEqual(result.mmc_analysis["expiry_minutes"], 5)

    def test_flat_market_returns_hold(self):
        result = generate_quotex_price_action_signal(make_candles(240, flat=True))
        self.assertEqual(result.action, "HOLD")

    def test_resampling_excludes_incomplete_higher_timeframe_bar(self):
        x = make_candles(241)
        m5 = _resample_closed(x, 5)
        self.assertTrue(((m5["timestamp"] + pd.Timedelta(minutes=5)) <= (x.iloc[-1]["timestamp"] + pd.Timedelta(minutes=1))).all())

    def test_confidence_is_not_win_probability(self):
        result = generate_quotex_price_action_signal(make_candles())
        self.assertEqual(result.mmc_analysis["confidence_basis"], "rule_strength_not_win_probability")


if __name__ == "__main__":
    unittest.main()
