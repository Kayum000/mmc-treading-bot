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


class ThirtyMinuteAnalysisTests(unittest.TestCase):
    def test_strategy_reports_30m_and_1h_context(self):
        result = generate_quotex_price_action_signal(candles())
        self.assertEqual(result.mmc_analysis["analysis_timeframe"], "30m")
        self.assertEqual(result.mmc_analysis["expiry_minutes"], 30)
        self.assertGreaterEqual(result.mmc_analysis.get("m30_count", 0), 20)
        self.assertGreaterEqual(result.mmc_analysis.get("h1_count", 0), 12)


    def test_native_m30_h1_history_works_with_short_m1_history(self):
        m1 = candles(300)
        m30 = candles(3000).iloc[::30].reset_index(drop=True)
        h1 = candles(3000).iloc[::60].reset_index(drop=True)
        result = generate_quotex_price_action_signal(m1, candles_30m=m30, candles_1h=h1)
        self.assertEqual(result.mmc_analysis["analysis_timeframe"], "30m")
        self.assertEqual(result.mmc_analysis["m30_count"], len(m30))
        self.assertEqual(result.mmc_analysis["h1_count"], len(h1))

    def test_incomplete_m30_bar_is_excluded(self):
        x = candles(1201)
        m30 = _resample_closed(x, 30)
        last_end = x.iloc[-1]["timestamp"] + pd.Timedelta(minutes=1)
        self.assertTrue(((m30["timestamp"] + pd.Timedelta(minutes=30)) <= last_end).all())

    def test_short_history_holds_instead_of_forcing_direction(self):
        result = generate_quotex_price_action_signal(candles(300))
        self.assertEqual(result.action, "HOLD")
        self.assertEqual(result.mmc_analysis["expiry_minutes"], 30)


if __name__ == "__main__":
    unittest.main()
