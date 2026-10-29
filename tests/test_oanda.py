import unittest
from unittest.mock import patch

import pandas as pd

from data.oanda import normalize_oanda_instrument, fetch_oanda_candles, fetch_oanda_quote


class OandaMarketDataTests(unittest.TestCase):
    def test_normalizes_compact_and_slash_pairs(self):
        self.assertEqual(normalize_oanda_instrument("EURUSD"), "EUR_USD")
        self.assertEqual(normalize_oanda_instrument("gbp/usd"), "GBP_USD")

    def test_rejects_otc_symbols(self):
        with self.assertRaises(ValueError):
            normalize_oanda_instrument("EURUSD_OTC")

    def test_requires_token_and_account(self):
        with patch.dict("os.environ", {"OANDA_ACCESS_TOKEN": "", "OANDA_ACCOUNT_ID": ""}):
            with self.assertRaisesRegex(RuntimeError, "OANDA_ACCESS_TOKEN"):
                fetch_oanda_candles("EURUSD")

    @patch("data.oanda._get")
    def test_only_completed_m1_candles_are_returned(self, mock_get):
        now = pd.Timestamp.now(tz="UTC").floor("min")
        completed = (now - pd.Timedelta(minutes=1)).isoformat()
        forming = now.isoformat()
        mock_get.return_value = {"candles": [
            {"time": completed, "complete": True, "mid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": "1.15"}},
            {"time": forming, "complete": False, "mid": {"o": "1.15", "h": "1.2", "l": "1.1", "c": "1.18"}},
        ]}
        # Current implementation requires 60 closed candles, so use the
        # normalization/validation helper contract through a 60-row fixture.
        mock_get.return_value["candles"] = [
            {"time": (now - pd.Timedelta(minutes=i+1)).isoformat(), "complete": True,
             "mid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": "1.15"}}
            for i in range(60)
        ] + [{"time": forming, "complete": False, "mid": {"o": "1.15", "h": "1.2", "l": "1.1", "c": "1.18"}}]
        with patch.dict("os.environ", {"OANDA_ACCESS_TOKEN": "test-token", "OANDA_ACCOUNT_ID": "test-account", "OANDA_ENVIRONMENT": "practice"}):
            frame = fetch_oanda_candles("EURUSD", count=120)
        self.assertEqual(len(frame), 60)
        self.assertTrue((frame["timestamp"] < now).all())
        self.assertEqual(frame.iloc[-1]["close"], 1.15)

    @patch("data.oanda._get")
    def test_fetches_live_bid_ask_midpoint(self, mock_get):
        mock_get.return_value = {"prices": [{
            "instrument": "EUR_USD",
            "time": pd.Timestamp.now(tz="UTC").isoformat(),
            "bids": [{"price": "1.1000", "liquidity": "1000"}],
            "asks": [{"price": "1.1002", "liquidity": "1000"}],
        }]}
        with patch.dict("os.environ", {"OANDA_ACCESS_TOKEN": "test-token", "OANDA_ACCOUNT_ID": "test-account", "OANDA_ENVIRONMENT": "practice"}):
            quote = fetch_oanda_quote("EURUSD")
        self.assertAlmostEqual(quote["price"], 1.1001)
        self.assertEqual(quote["instrument"], "EUR_USD")


if __name__ == "__main__":
    unittest.main()
