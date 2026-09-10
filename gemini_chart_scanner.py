"""Gemini Vision backend for the independent chart scanner.

Keeps the existing MMC strategy untouched. The scanner receives a chart image
as a data URL and asks Gemini for a validated BUY/SELL/AVOID JSON decision.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request


DEFAULT_MODEL = "gemini-3.1-flash-lite"


def _mime_and_bytes(data_url: str) -> tuple[str, str]:
    try:
        header, encoded = data_url.split(",", 1)
        mime = header.split(":", 1)[1].split(";", 1)[0].lower()
        raw = base64.b64decode(encoded, validate=True)
        return mime, raw
    except Exception as exc:
        raise ValueError("Invalid chart image data.") from exc


def _extract_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    texts = [str(part.get("text", "")) for part in parts if part.get("text")]
    return "\n".join(texts).strip()


def analyze_image(data_url: str, analysis_time_bd: str, pair: str) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "setup_required": True,
            "error": "Chart Scanner-এর জন্য GEMINI_API_KEY এখনো Render-এ সেট করা হয়নি।",
        }

    model = os.getenv("CHART_SCANNER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    mime_type, raw = _mime_and_bytes(data_url)
    encoded = base64.b64encode(raw).decode("ascii")

    prompt = f"""
You are the independent visual chart scanner inside an FX/crypto dashboard.
Analyze ONLY the supplied chart image. Do not invent prices, candles, indicators,
support/resistance levels, or market data that are not visible.

Selected market: {pair or 'unknown'}
Analysis time (Bangladesh): {analysis_time_bd}

Inspect visible candles, trend/market structure, support/resistance, breakouts or
fakeouts, momentum, volatility, and any clearly visible indicators. If the image
is unclear, cropped, stale, lacks enough candles, or does not provide enough
visible evidence for a directional decision, choose AVOID.

A BUY or SELL decision requires multiple visible confirmations. Do not produce a
signal merely because one candle or one indicator looks favorable. This is a
research/prototyping scanner, not a guarantee of profitable trading.

Return ONLY a JSON object matching the requested schema. signal_time_bd must be
exactly the supplied analysis time. confidence must reflect the strength of the
visible evidence, not certainty.
""".strip()

    schema = {
        "type": "object",
        "properties": {
            "signal": {"type": "string", "enum": ["BUY", "SELL", "AVOID"]},
            "signal_time_bd": {"type": "string"},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "trend": {"type": "string"},
            "reason": {"type": "string"},
            "risk": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        },
        "required": [
            "signal",
            "signal_time_bd",
            "confidence",
            "trend",
            "reason",
            "risk",
        ],
        "additionalProperties": False,
    }

    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": encoded,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }

    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + urllib.parse.quote(model, safe="")
        + ":generateContent?key="
        + urllib.parse.quote(api_key, safe="")
    )
    request_body = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        return {"ok": False, "error": f"Gemini Vision API error ({exc.code}): {detail}"}
    except Exception as exc:
        return {"ok": False, "error": f"Gemini Chart Scanner connection error: {exc}"}

    text = _extract_text(payload)
    if not text:
        return {"ok": False, "error": "Gemini returned an empty chart-analysis response."}

    try:
        result = json.loads(text)
    except Exception:
        return {"ok": False, "error": "Gemini response JSON format-এ পাওয়া যায়নি।"}

    signal = str(result.get("signal", "AVOID")).upper()
    if signal not in {"BUY", "SELL", "AVOID"}:
        signal = "AVOID"
    try:
        confidence = max(0, min(100, int(result.get("confidence", 0))))
    except Exception:
        confidence = 0

    return {
        "ok": True,
        "signal": signal,
        "signal_time_bd": str(result.get("signal_time_bd") or analysis_time_bd),
        "confidence": confidence,
        "trend": str(result.get("trend", "—")),
        "reason": str(result.get("reason", "—")),
        "risk": str(result.get("risk", "HIGH")).upper(),
        "model": model,
        "provider": "gemini",
        "independent": True,
    }
