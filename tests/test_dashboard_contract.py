from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
SIGNAL = (ROOT / "signals" / "get_signal.py").read_text(encoding="utf-8")


def test_dashboard_navigation_targets_exist():
    hrefs = re.findall(r'<a[^>]+href="(#[-\w]+)"', TEMPLATE)
    targets = set(re.findall(r'id="([-\w]+)"', TEMPLATE))
    missing = [href[1:] for href in hrefs if href[1:] not in targets]
    assert not missing, f"Dashboard navigation target(s) missing: {missing}"


def test_dashboard_core_routes_are_present():
    for route in ("/", "/select-market", "/auto-signal", "/performance", "/news-alert", "/news-direction"):
        assert f'@app.route("{route}"' in APP


def test_market_selection_is_session_driven_not_hard_coded_to_eurusd():
    assert 'session.get("selected_pair", "")' in APP
    assert 'session["selected_pair"] = pair' in APP
    assert 'if pair not in _valid_pairs(mode)' in APP
    # EUR/USD remains a supported market, but it must not be the implicit GET SIGNAL choice.
    assert 'pair = session.get("selected_pair", "")' in APP
    assert 'mode, pair = "", ""' in APP


def test_signal_payload_exposes_score_without_removing_existing_fields():
    assert '"buy_score"' in SIGNAL
    assert '"sell_score"' in SIGNAL
    assert '"signal_score"' in SIGNAL
    assert '"score_bucket"' in SIGNAL
    assert '"confidence"' in SIGNAL
    assert '"reason"' in SIGNAL


def test_user_facing_reason_translation_is_bengali():
    assert 'def _bengali_reason' in SIGNAL
    assert "Insufficient or conflicting confirmation" in SIGNAL
    assert "যথেষ্ট কনফার্মেশন পাওয়া যায়নি" in SIGNAL
    assert "spread too wide" in SIGNAL
    assert "স্প্রেড বেশি" in SIGNAL


def test_real_market_registry_has_twenty_pairs():
    expected = (
        "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
        "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "GBP/CHF",
        "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY", "EUR/AUD", "GBP/AUD",
        "AUD/CAD", "NZD/CAD",
    )
    for pair in expected:
        assert f'"{pair}"' in APP


def test_otc_signal_uses_detected_active_market_when_available():
    assert "detected_asset = local_active_asset()" in SIGNAL
    assert "pair = display_for_asset(detected_asset) or requested_pair" in SIGNAL
    assert "asset_for_display(pair)" in SIGNAL
