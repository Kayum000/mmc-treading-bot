import unittest
from unittest.mock import patch
import pandas as pd

from strategy.quotex_price_action import generate_quotex_price_action_signal, _resample_closed, _structure_bias, _technical_confirmation_matrix


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


class OneMinuteForexStructureStrategyTests(unittest.TestCase):
    def test_insufficient_history_returns_hold(self):
        result = generate_quotex_price_action_signal(make_candles(90))
        self.assertEqual(result.action, "HOLD")
        self.assertEqual(result.mmc_analysis["expiry_minutes"], 1)

    def test_flat_market_returns_hold(self):
        result = generate_quotex_price_action_signal(make_candles(900, flat=True))
        self.assertEqual(result.action, "HOLD")

    def test_indicator_votes_cannot_trigger_without_price_action_setup(self):
        matrix = {"total": 127, "buy": 127, "sell": 0, "neutral": 0,
                  "direction": "BUY", "agreement": 1.0, "checks": {}}
        with patch("strategy.quotex_price_action._technical_confirmation_matrix", return_value=matrix):
            result = generate_quotex_price_action_signal(make_candles(900, flat=True))
        self.assertEqual(result.action, "HOLD")
        self.assertFalse(result.mmc_analysis["indicator_vote_summary"]["used_for_signal"])

    def test_resampling_excludes_incomplete_higher_timeframe_bar(self):
        x = make_candles(241)
        m5 = _resample_closed(x, 5)
        self.assertTrue(((m5["timestamp"] + pd.Timedelta(minutes=5)) <= (x.iloc[-1]["timestamp"] + pd.Timedelta(minutes=1))).all())

    def test_127_parameterized_technical_confirmations_are_returned(self):
        matrix = _technical_confirmation_matrix(make_candles(900))
        self.assertEqual(matrix["total"], 127)
        self.assertEqual(len(matrix["checks"]), 127)
        self.assertEqual(matrix["buy"] + matrix["sell"] + matrix["neutral"], 127)

    def test_confidence_is_not_win_probability(self):
        result = generate_quotex_price_action_signal(make_candles(900))
        self.assertEqual(result.mmc_analysis["confidence_basis"], "rule_strength_not_win_probability")


if __name__ == "__main__":
    unittest.main()
