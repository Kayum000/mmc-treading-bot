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
_SENDING: set[str] = set()
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
    try:
        response = requests.post(
            f"{_API}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=12,
        )
    except requests.RequestException as exc:
        # Do not include the exception text: requests may include the bot token URL.
        raise RuntimeError(f"Telegram sendMessage request failed ({type(exc).__name__}).") from None

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not response.ok or not payload.get("ok"):
        # Telegram's description (e.g. "chat not found") is useful for diagnosis.
        # Never raise HTTPError here, because its message includes the token-bearing URL.
        description = str(payload.get("description") or "Telegram returned no error description.")
        raise RuntimeError(f"Telegram sendMessage failed (HTTP {response.status_code}): {description}")
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
        if key in _SENT or key in _SENDING:
            return False
        _SENDING.add(key)

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
    signal_number = result.get("signal_number", "—")
    wins = int(result.get("wins") or 0)
    losses = int(result.get("losses") or 0)
    strategy = str(result.get("strategy") or "Adaptive").replace("_", " ").strip()
    regime = str(result.get("regime") or "").replace("_", " ").strip()
    strategy_line = f"🧠 Strategy: {strategy}" + (f" • {regime}" if regime and regime.upper() != "N/A" else "")
    message = (
        "👑 MMC ELITE VIP\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{'🟢 BUY' if action == 'BUY' else '🔴 SELL'} SIGNAL  •  PREMIUM ALERT\n"
        f"🔢 Signal ID: #{signal_number}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💱 Pair: {pair}\n"
        f"🏦 Market: {mode}\n"
        f"🎯 Direction: {'BUY 🟢' if action == 'BUY' else 'SELL 🔴'}\n"
        f"💵 Entry Price: {price_text}\n"
        f"⏳ Expiry: 1 Minute\n"
        f"🕒 Signal Time (BD): {entry_time or 'N/A'}\n"
        f"📡 Source: {result.get('source') or '—'}\n"
        f"{strategy_line}\n"
        f"📈 Confidence: {confidence_text}\n"
        f"📝 Reason: {reason[:500]}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Signal only; outcomes are not guaranteed. Manage your risk."
    )
    try:
        _post_message(message)
    except Exception:
        with _LOCK:
            _SENDING.discard(key)
        raise
    with _LOCK:
        _SENDING.discard(key)
        _SENT.add(key)
        _SENT_ORDER.append(key)
        while len(_SENT_ORDER) > _MAX_REMEMBERED:
            expired = _SENT_ORDER.pop(0)
            _SENT.discard(expired)
    return True

def notify_signal_result(result: dict[str, Any]) -> bool:
    """Send a finalized signal outcome once the matching entry candle closes."""
    if not telegram_enabled() or not isinstance(result, dict):
        return False
    outcome = str(result.get("result") or "").strip()
    labels = {"লাভ": "🟢 WIN", "লস": "🔴 LOSS", "DOJI": "🟡 DOJI"}
    label = labels.get(outcome)
    if not label:
        return False
    pair = str(result.get("pair") or "Unknown pair").strip()
    mode = str(result.get("market_mode") or "unknown").replace("_", " ").upper()
    signal = str(result.get("signal") or "").strip().upper()
    entry_time = str(result.get("signal_time_utc") or "")
    price = result.get("outcome_price")
    try:
        price_text = f"{float(price):.8f}".rstrip("0").rstrip(".") if price is not None else "N/A"
    except (TypeError, ValueError):
        price_text = str(price)
    signal_number = result.get("signal_number", "—")
    wins = int(result.get("wins") or 0)
    losses = int(result.get("losses") or 0)
    total_decided = wins + losses
    win_rate = f"{(wins / total_decided) * 100:.1f}%" if total_decided else "N/A"
    entry_price = result.get("entry_price")
    try:
        entry_price_text = f"{float(entry_price):.8f}".rstrip("0").rstrip(".") if entry_price is not None else "N/A"
    except (TypeError, ValueError):
        entry_price_text = str(entry_price)
    strategy = str(result.get("strategy") or "").replace("_", " ").strip()
    strategy_line = f"🧠 Strategy: {strategy}\n" if strategy else ""
    message = (
        "👑 MMC ELITE RESULT\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{label}\n"
        f"🔢 Signal ID: #{signal_number}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💱 Pair: {pair}\n"
        f"🏦 Market: {mode}\n"
        f"🎯 Direction: {signal or 'N/A'}\n"
        f"💵 Entry Price: {entry_price_text}\n"
        f"🏁 Result Price: {price_text}\n"
        f"🕒 Entry Candle (UTC): {entry_time or 'N/A'}\n"
        f"{strategy_line}"
        "📊 PERFORMANCE STATS\n"
        f"🟢 Total WIN: {wins}   🔴 Total LOSS: {losses}\n"
        f"🏆 Win Rate: {win_rate}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Result based on the completed 1-minute candle."
    )
    _post_message(message)
    return True

