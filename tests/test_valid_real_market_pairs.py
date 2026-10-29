import unittest
from unittest.mock import patch

from web import app as dashboard


class ValidRealMarketPairTests(unittest.TestCase):
    @patch("data.biquote.known_biquote_symbols", return_value=[])
    def test_accepts_compact_fallback_symbol_and_slash_pair(self, _known_symbols):
        with patch.object(dashboard, "REAL_PAIRS", ["EUR/USD", "GBP/USD"]):
            valid = dashboard._valid_pairs("real")
        self.assertIn("EUR/USD", valid)
        self.assertIn("EURUSD", valid)
        self.assertIn("GBP/USD", valid)
        self.assertIn("GBPUSD", valid)

    @patch("data.biquote.known_biquote_symbols", return_value=["XAUUSD", "BTCUSD"])
    def test_keeps_catalog_symbols_available(self, _known_symbols):
        with patch.object(dashboard, "REAL_PAIRS", ["EUR/USD"]):
            valid = dashboard._valid_pairs("real")
        self.assertIn("EURUSD", valid)
        self.assertIn("XAUUSD", valid)
        self.assertIn("BTCUSD", valid)

    def test_otc_validation_is_unchanged(self):
        with patch.object(dashboard, "QUOTEX_OTC_PAIRS", ["EURUSD_OTC"]):
            self.assertEqual(dashboard._valid_pairs("quotex_otc"), ["EURUSD_OTC"])


if __name__ == "__main__":
    unittest.main()
