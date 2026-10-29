import os
import unittest
from unittest.mock import patch

from web import app as dashboard


class UsageProviderTests(unittest.TestCase):
    def setUp(self):
        self.old_cache = dict(dashboard._USAGE_CACHE)
        dashboard._USAGE_CACHE.update(data=None, at=0.0)

    def tearDown(self):
        dashboard._USAGE_CACHE.update(self.old_cache)

    def _usage_for(self, provider):
        dashboard._USAGE_CACHE.update(data=None, at=0.0)
        with patch.dict(os.environ, {"MARKET_DATA_PROVIDER": provider}):
            return dashboard._usage_view()["api"]

    def test_biquote_is_reported_as_provider(self):
        api = self._usage_for("biquote")
        self.assertEqual(api["provider"], "biquote public REST API")
        self.assertFalse(api["api_key_required"])

    def test_oanda_is_reported_as_keyed_provider(self):
        api = self._usage_for("oanda")
        self.assertEqual(api["provider"], "OANDA v20 REST API")
        self.assertTrue(api["api_key_required"])

    def test_browser_collector_is_reported_when_configured(self):
        api = self._usage_for("browser")
        self.assertEqual(api["provider"], "Quotex browser WebSocket collector")
        self.assertFalse(api["api_key_required"])


if __name__ == "__main__":
    unittest.main()
