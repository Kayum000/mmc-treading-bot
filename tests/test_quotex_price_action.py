import pandas as pd

from strategy.quotex_price_action import generate_quotex_price_action_signal


def candles(count=100, flat=False):
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=count, freq="min")
    rows = []
    price = 100.0
    for i, stamp in enumerate(timestamps):
        if flat:
            op = close = price
            high = price + 0.01
            low = price - 0.01
        else:
            drift = 0.03 if (i % 7) not in (4, 5) else -0.01
            op = price
            close = price + drift
            high = max(op, close) + 0.02
            low = min(op, close) - 0.02
            price = close
        rows.append({
            "timestamp": stamp, "open": op, "high": high, "low": low, "close": close,
        })
    return pd.DataFrame(rows)


def test_insufficient_history_returns_hold():
    result = generate_quotex_price_action_signal(candles(25))
    assert result.action == "HOLD"
    assert result.confidence == 0.0
    assert result.mmc_analysis["candle_count"] == 25


def test_flat_market_returns_hold_instead_of_forced_direction():
    result = generate_quotex_price_action_signal(candles(120, flat=True))
    assert result.action == "HOLD"
    assert result.regime == "NO_TRADE"


def test_missing_required_columns_returns_hold():
    result = generate_quotex_price_action_signal(pd.DataFrame({"close": [1, 2, 3]}))
    assert result.action == "HOLD"
    assert result.regime == "NO_TRADE"


def test_strategy_never_reports_confidence_as_win_probability():
    result = generate_quotex_price_action_signal(candles(100))
    assert result.mmc_analysis["confidence_basis"] == "rule_strength_not_win_probability"
    if result.action == "HOLD":
        assert result.confidence == 0.0
