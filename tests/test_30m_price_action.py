import unittest
import pandas as pd

from strategy.quotex_price_action import generate_quotex_price_action_signal, _resample_closed


def candles(count=1200):
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=count, freq="min")
    rows, price = [], 100.0
    for i, stamp in enumerate(timestamps):
        drift = 0.04 if (i % 9) not in (6, 7) else -0.015
        op = price
        close = price + drift
        rows.append({"timestamp": stamp, "open": op, "high": max(op, close) + 0.025,
                     "low": min(op, close) - 0.025, "close": close})
        price = close
    return pd.DataFrame(rows)


class OneMinuteAnalysisTests(unittest.TestCase):
    def test_strategy_reports_m1_with_m5_m15_context(self):
        result = generate_quotex_price_action_signal(candles())
        self.assertEqual(result.mmc_analysis["analysis_timeframe"], "1m")
        self.assertEqual(result.mmc_analysis["expiry_minutes"], 1)
        self.assertGreaterEqual(result.mmc_analysis.get("m5_count", 0), 12)
        self.assertGreaterEqual(result.mmc_analysis.get("m15_count", 0), 4)
        self.assertEqual(result.strategy, "FOREX_STRUCTURE_PA_M1_MTF")

    def test_short_history_holds_instead_of_forcing_direction(self):
        result = generate_quotex_price_action_signal(candles(45))
        self.assertEqual(result.action, "HOLD")
        self.assertEqual(result.mmc_analysis["expiry_minutes"], 1)

    def test_incomplete_m5_bar_is_excluded(self):
        x = candles(121)
        m5 = _resample_closed(x, 5)
        last_end = x.iloc[-1]["timestamp"] + pd.Timedelta(minutes=1)
        self.assertTrue(((m5["timestamp"] + pd.Timedelta(minutes=5)) <= last_end).all())

    def test_incomplete_m15_bar_is_excluded(self):
        x = candles(121)
        m15 = _resample_closed(x, 15)
        last_end = x.iloc[-1]["timestamp"] + pd.Timedelta(minutes=1)
        self.assertTrue(((m15["timestamp"] + pd.Timedelta(minutes=15)) <= last_end).all())


if __name__ == "__main__":
    unittest.main()
