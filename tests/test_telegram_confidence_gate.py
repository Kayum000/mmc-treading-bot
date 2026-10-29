import os
import unittest
from unittest.mock import patch

from notifications.telegram import notify_signal


class TelegramConfidenceGateTests(unittest.TestCase):
    def test_directional_signal_at_54_percent_is_sent(self):
        result = {
            "signal": "BUY",
            "pair": "EUR/USD",
            "confidence": 0.54,
            "entry_time_bd": "2026-10-29 18:00:00",
        }
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "test-chat",
            "TELEGRAM_SIGNALS_ENABLED": "true",
        }), patch("notifications.telegram._post_message", return_value={"ok": True}) as send:
            self.assertTrue(notify_signal(result))
            send.assert_called_once()

    def test_directional_signal_below_50_percent_is_suppressed(self):
        result = {"signal": "SELL", "pair": "EUR/USD", "confidence": 0.49}
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "test-chat",
            "TELEGRAM_SIGNALS_ENABLED": "true",
        }), patch("notifications.telegram._post_message") as send:
            self.assertFalse(notify_signal(result))
            send.assert_not_called()

    def test_hold_is_never_sent(self):
        result = {"signal": "HOLD", "pair": "EUR/USD", "confidence": 0.80}
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "test-chat",
            "TELEGRAM_SIGNALS_ENABLED": "true",
        }), patch("notifications.telegram._post_message") as send:
            self.assertFalse(notify_signal(result))
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
