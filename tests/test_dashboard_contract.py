from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
SIGNAL = (ROOT / "signals" / "get_signal.py").read_text(encoding="utf-8")


class DashboardContractTests(unittest.TestCase):
    def test_dashboard_navigation_targets_exist(self):
        hrefs = re.findall(r'<a[^>]+href="(#[-\w]+)"', TEMPLATE)
        targets = set(re.findall(r'id="([-\w]+)"', TEMPLATE))
        runtime_targets = {"live-market-chart", "master-control-overlay"}
        missing = [href[1:] for href in hrefs if href[1:] not in targets and href[1:] not in runtime_targets]
        self.assertFalse(missing, f"Dashboard navigation target(s) missing: {missing}")
        self.assertIn("dashboard_functional.js", APP)

    def test_dashboard_core_routes_are_present(self):
        for route in ("/", "/select-market", "/auto-signal", "/performance", "/news-alert", "/news-direction"):
            self.assertIn(f'@app.route("{route}"', APP)

    def test_market_selection_is_session_driven_not_hard_coded_to_eurusd(self):
        self.assertIn('session.get("selected_pair", "")', APP)
        self.assertIn('session["selected_pair"] = pair', APP)
        self.assertIn('if pair not in _valid_pairs(mode)', APP)
        self.assertIn('pair = session.get("selected_pair", "")', APP)
        self.assertIn('mode, pair = "", ""', APP)

    def test_signal_payload_exposes_score_without_removing_existing_fields(self):
        for field in ('"buy_score"', '"sell_score"', '"signal_score"', '"score_bucket"', '"confidence"', '"reason"'):
            self.assertIn(field, SIGNAL)

    def test_user_facing_reason_translation_is_bengali(self):
        self.assertIn('def _bengali_reason', SIGNAL)
        self.assertIn("Insufficient or conflicting confirmation", SIGNAL)
        self.assertIn("যথেষ্ট কনফার্মেশন পাওয়া যায়নি", SIGNAL)
        self.assertIn("spread too wide", SIGNAL)
        self.assertIn("স্প্রেড বেশি", SIGNAL)

    def test_real_market_registry_has_twenty_pairs(self):
        expected = (
            "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
            "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "GBP/CHF",
            "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY", "EUR/AUD", "GBP/AUD",
            "AUD/CAD", "NZD/CAD",
        )
        for pair in expected:
            self.assertIn(f'"{pair}"', APP)

    def test_otc_signal_uses_detected_active_market_when_available(self):
        self.assertIn("detected_asset = local_active_asset()", SIGNAL)
        self.assertIn("pair = display_for_asset(detected_asset) or requested_pair", SIGNAL)
        self.assertIn("asset_for_display(pair)", SIGNAL)


if __name__ == "__main__":
    unittest.main()
