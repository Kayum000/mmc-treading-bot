import unittest
from unittest.mock import patch

import pandas as pd

from data.twelve_data import normalize_forex_symbol, fetch_twelve_data_candles


class TwelveDataForexTests(unittest.TestCase):
    def test_normalizes_compact_pair(self):
        self.assertEqual(normalize_forex_symbol("EURUSD"), "EUR/USD")

    def test_normalizes_slash_pair(self):
        self.assertEqual(normalize_forex_symbol("gbp/usd"), "GBP/USD")

    def test_rejects_non_forex_symbol(self):
        with self.assertRaises(ValueError):
            normalize_forex_symbol("EURUSD_OTC")

    def test_requires_server_api_key(self):
        with patch.dict("os.environ", {"TWELVEDATA_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "TWELVEDATA_API_KEY"):
                fetch_twelve_data_candles("EUR/USD")


if __name__ == "__main__":
    unittest.main()
