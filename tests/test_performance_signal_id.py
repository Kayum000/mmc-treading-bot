"""Focused regression tests for performance signal deduplication.

Extract the production helper from web/app.py's AST so the tests do not import
the web app, start background workers, or require production integrations.
"""
import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "web" / "app.py"


def _utc_epoch(value):
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _load_production_signal_id():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "_performance_signal_id"
    )
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"_utc_epoch": _utc_epoch}
    exec(compile(module, str(APP_PATH), "exec"), namespace)
    return namespace["_performance_signal_id"]


class PerformanceSignalIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signal_id = staticmethod(_load_production_signal_id())

    def test_same_entry_minute_deduplicates_even_if_analysis_time_changes(self):
        first = self.signal_id(
            "quotex_otc", "EUR/USD OTC", "BUY", "2026-10-10T12:34:02Z"
        )
        second = self.signal_id(
            "quotex_otc", "EUR/USD OTC", "BUY", "2026-10-10T12:34:58Z"
        )
        self.assertEqual(first, second)

    def test_next_entry_minute_is_a_distinct_signal(self):
        first = self.signal_id("real", "EUR/USD", "BUY", "2026-10-10T12:34:59Z")
        second = self.signal_id("real", "EUR/USD", "BUY", "2026-10-10T12:35:00Z")
        self.assertNotEqual(first, second)

    def test_market_pair_and_direction_remain_part_of_identity(self):
        base = self.signal_id("real", "EUR/USD", "BUY", "2026-10-10T12:34:10Z")
        variants = [
            self.signal_id("quotex_otc", "EUR/USD", "BUY", "2026-10-10T12:34:10Z"),
            self.signal_id("real", "GBP/USD", "BUY", "2026-10-10T12:34:10Z"),
            self.signal_id("real", "EUR/USD", "SELL", "2026-10-10T12:34:10Z"),
        ]
        self.assertEqual(len(set([base, *variants])), 4)

    def test_invalid_timestamps_do_not_collapse_into_one_minute(self):
        first = self.signal_id("real", "EUR/USD", "BUY", "legacy-time-a")
        second = self.signal_id("real", "EUR/USD", "BUY", "legacy-time-b")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
