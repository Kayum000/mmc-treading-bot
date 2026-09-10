"""Vision-based chart scanner.

This module is deliberately separate from the live tick strategy. It reads a
user-supplied chart image and asks a vision model for a structured BUY/SELL/
AVOID opinion with an exact scan time. It never changes the live v2.1 engine.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone


def analyze_chart_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "error": "Chart Scanner is not configured yet: OPENAI_API_KEY is missing on the server.",
            "needs_api_key": True,
        }

    if not image_bytes:
        return {"ok": False, "error": "No chart image was received."}
    if len(image_bytes) > 12 * 1024 * 1024:
        return {"ok": False, "error": "Chart image is too large. Maximum size is 12 MB."}

    if mime_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        mime_type = "image/jpeg"

    try:
        from openai import OpenAI
    except ImportError as exc:
        return {"ok": False, "error": "OpenAI SDK is not installed on the server."}

    image_data = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{image_data}"

    prompt = """
You are the chart-scanning engine for an FX 1-minute trading dashboard.
Analyze ONLY what is visibly present in the supplied chart image. Do not invent
prices, indicators, candles, support/resistance levels, or volume that cannot be
read. If the chart is unclear, choose AVOID.

Return ONLY valid JSON with exactly these fields:
{
  "signal": "BUY" | "SELL" | "AVOID",
  "confidence": number,
  "entry_time": "HH:MM:SS" | null,
  "reason": string,
  "market_state": string,
  "patterns": [string]
}

Rules:
- The scan time is the moment this request is processed. Treat the requested
  entry time as NOW / the signal timestamp, not the next candle.
- BUY means the visible structure supports upward continuation; SELL means
  downward continuation.
- AVOID when evidence is mixed, the chart is too unclear, or there is no clean
  setup.
- Confidence must be 0-100 and should reflect visual evidence, not certainty.
- Keep reason concise and mention only visible evidence.
"""

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=os.getenv("CHART_SCAN_MODEL", "gpt-5.6-luna"),
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url, "detail": "high"},
                    ],
                }
            ],
        )
        text = getattr(response, "output_text", "") or ""
        parsed = json.loads(text)
    except Exception as exc:
        return {"ok": False, "error": f"Chart analysis failed: {exc}"}

    signal = str(parsed.get("signal", "AVOID")).upper()
    if signal not in {"BUY", "SELL", "AVOID"}:
        signal = "AVOID"
    try:
        confidence = max(0.0, min(100.0, float(parsed.get("confidence", 0))))
    except Exception:
        confidence = 0.0

    now = datetime.now(timezone.utc)
    return {
        "ok": True,
        "signal": signal,
        "confidence": round(confidence, 1),
        "entry_time": parsed.get("entry_time"),
        "signal_time_utc": now.isoformat(),
        "reason": str(parsed.get("reason", ""))[:500],
        "market_state": str(parsed.get("market_state", ""))[:120],
        "patterns": [str(x)[:80] for x in (parsed.get("patterns") or [])][:8],
        "source": "chart_camera",
        "strategy": "visual_chart_scan",
    }
