"""Telegram notifications for newly generated MMC BUY/SELL signals.

Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as deployment secrets.
The bot sends signals only; it never places trades.
"""
from __future__ import annotations

import os
import threading
from typing import Any

import requests

_API = "https://api.telegram.org"
_LOCK = threading.Lock()
_SENT: set[str] = set()
_SENT_ORDER: list[str] = []
_MAX_REMEMBERED = 2000


def _config() -> tuple[str, str]:
    return (
        (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip(),
        (os.getenv("TELEGRAM_CHAT_ID") or "").strip(),
    )


def telegram_enabled() -> bool:
    token, chat_id = _config()
    return bool(token and chat_id and os.getenv("TELEGRAM_SIGNALS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"})


def _post_message(text: str) -> dict[str, Any]:
    token, chat_id = _config()
    if not token or not chat_id:
        raise RuntimeError("Telegram is not configured: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
    response = requests.post(
        f"{_API}/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("description") or "Telegram sendMessage failed"))
    return payload


def send_test_message() -> dict[str, Any]:
    """Send a user-requested test message to the configured chat."""
    if not telegram_enabled():
        raise RuntimeError("Telegram notifications are disabled or missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.")
    return _post_message("✅ MMC Trading Bot: Telegram connection test successful. Signal alerts are enabled.")


def get_recent_chats() -> list[dict[str, Any]]:
    """Read recent bot updates to help the owner identify a chat ID after /start."""
    token, _chat_id = _config()
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in the hosting environment first.")
    response = requests.get(f"{_API}/bot{token}/getUpdates", timeout=12)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("description") or "Telegram getUpdates failed"))
    chats: dict[str, dict[str, Any]] = {}
    for update in payload.get("result", []):
        message = update.get("message") or update.get("channel_post") or update.get("my_chat_member") or {}
        chat = message.get("chat") or {}
        if chat.get("id") is not None:
            chat_id = str(chat["id"])
            chats[chat_id] = {
                "chat_id": chat_id,
                "type": chat.get("type"),
                "title": chat.get("title") or chat.get("username") or chat.get("first_name") or "",
            }
    return list(chats.values())


def notify_signal(result: dict[str, Any]) -> bool:
    """Send each BUY/SELL signal once per process; HOLD responses are ignored."""
    if not telegram_enabled() or not isinstance(result, dict):
        return False
    action = str(result.get("signal") or result.get("entry_signal") or "").strip().upper()
    if action not in {"BUY", "SELL"}:
        return False

    pair = str(result.get("pair") or "Unknown pair").strip()
    mode = str(result.get("market_mode") or "unknown").replace("_", " ").upper()
    entry_time = str(result.get("entry_time_bd") or result.get("signal_time_bd") or result.get("signal_time_utc") or "")
    analysis_time = str(result.get("analysis_candle_time_utc") or "")
    key = "|".join((pair, mode, action, entry_time, analysis_time))
    with _LOCK:
        if key in _SENT:
            return False

    confidence = result.get("confidence")
    try:
        confidence_text = f"{float(confidence) * 100:.0f}%" if confidence is not None else "N/A"
    except (TypeError, ValueError):
        confidence_text = "N/A"
    entry_price = result.get("entry_price")
    try:
        price_text = f"{float(entry_price):.6f}".rstrip("0").rstrip(".") if entry_price is not None else "Not available"
    except (TypeError, ValueError):
        price_text = str(entry_price)
    reason = str(result.get("reason") or "—").strip()
    message = (
        f"{'🟢 BUY' if action == 'BUY' else '🔴 SELL'} SIGNAL — MMC\n"
        f"Pair: {pair}\n"
        f"Market: {mode}\n"
        f"Entry reference: {price_text}\n"
        f"Entry time (BD): {entry_time or 'N/A'}\n"
        f"Confidence: {confidence_text}\n"
        f"Strategy: {result.get('strategy') or 'adaptive'} / {result.get('regime') or 'N/A'}\n"
        f"Reason: {reason[:700]}\n\n"
        "⚠️ Signal only, not a guarantee of profit. Verify the market and manage risk."
    )
    _post_message(message)
    with _LOCK:
        _SENT.add(key)
        _SENT_ORDER.append(key)
        while len(_SENT_ORDER) > _MAX_REMEMBERED:
            expired = _SENT_ORDER.pop(0)
            _SENT.discard(expired)
    return True
