import unittest
from unittest.mock import patch

import pandas as pd

from data.biquote import normalize_biquote_symbol, fetch_biquote_candles, fetch_biquote_quote


class BiquoteForexTests(unittest.TestCase):
    def test_normalizes_compact_pair(self):
        self.assertEqual(normalize_biquote_symbol("EURUSD"), "EURUSD")

    def test_normalizes_slash_pair(self):
        self.assertEqual(normalize_biquote_symbol("gbp/usd"), "GBPUSD")

    def test_rejects_non_forex_symbol(self):
        with self.assertRaises(ValueError):
            normalize_biquote_symbol("EURUSD_OTC")

    @patch("data.biquote.requests.get")
    def test_returns_only_closed_candles_in_ascending_order(self, get):
        now = pd.Timestamp.now(tz="UTC").floor("min")
        get.return_value.raise_for_status.return_value = None
        get.return_value.json.return_value = {"bars": [
            {"openTime": (now - pd.Timedelta(minutes=1)).isoformat(), "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "isOpen": True},
            {"openTime": (now - pd.Timedelta(minutes=2)).isoformat(), "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "isOpen": False}
        ]}
        frame = fetch_biquote_candles("EURUSD")
        self.assertEqual(len(frame), 1)
        self.assertEqual(float(frame.iloc[0]["close"]), 1.05)
        self.assertEqual(frame.iloc[0]["timestamp"], now - pd.Timedelta(minutes=2))

    @patch("data.biquote.requests.get")
    def test_requires_fresh_bid_ask_quote(self, get):
        now = pd.Timestamp.now(tz="UTC")
        get.return_value.raise_for_status.return_value = None
        get.return_value.json.return_value = {"bid": 1.1, "ask": 1.1002, "mid": 1.1001,
            "timestamp": now.isoformat(), "stale": False, "marketState": "open", "quoteAgeSeconds": 0}
        quote = fetch_biquote_quote("EURUSD")
        self.assertAlmostEqual(quote["price"], 1.1001)
        self.assertEqual(quote["symbol"], "EURUSD")


if __name__ == "__main__":
    unittest.main()
