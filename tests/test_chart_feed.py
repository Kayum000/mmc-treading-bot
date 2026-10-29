import os
import unittest
from unittest.mock import patch

import pandas as pd
from flask import Flask

import quotex_browser_ingest


class BiquoteChartEndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test-only"
        quotex_browser_ingest.init_quotex_browser_ingest(self.app)
        self.client = self.app.test_client()
        quotex_browser_ingest._PROVIDER_CHART_CACHE.clear()

    def test_real_chart_uses_biquote_without_api_key(self):
        frame = pd.DataFrame([{
            "timestamp": pd.Timestamp("2026-10-27T12:00:00Z"),
            "open": 1.10,
            "high": 1.11,
            "low": 1.09,
            "close": 1.105,
        }])
        with patch.dict(os.environ, {"MARKET_DATA_PROVIDER": "biquote"}, clear=False), patch(
            "data.biquote.fetch_biquote_candles", return_value=frame
        ) as fetch, patch(
            "data.biquote.fetch_biquote_quote",
            return_value={"price": 1.105, "bid": 1.1049, "ask": 1.1051, "timestamp": 1793102400, "age_seconds": 0}
        ):
            response = self.client.get("/quotex/real-market?asset=EURUSD")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["source"], "biquote live bid/ask + completed M1 candles")
        self.assertEqual(payload["bars"][0]["close"], 1.105)
        self.assertEqual(payload["quote"]["price"], 1.105)
        fetch.assert_called_once_with("EURUSD", count=180)

    def test_provider_failure_does_not_fall_back_to_quotex_prices(self):
        with patch.dict(os.environ, {"MARKET_DATA_PROVIDER": "biquote"}, clear=False), patch(
            "data.biquote.fetch_biquote_candles", side_effect=RuntimeError("provider unavailable")
        ):
            response = self.client.get("/quotex/real-market?asset=EURUSD")

        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["bars"], [])
        self.assertEqual(payload["source"], "biquote live bid/ask + completed M1 candles")


if __name__ == "__main__":
    unittest.main()
