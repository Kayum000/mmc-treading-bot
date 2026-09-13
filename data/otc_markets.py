"""Shared Quotex OTC market registry.

The registry is intentionally separate from strategy logic. It only defines
supported OTC symbols and their dashboard labels.
"""
from __future__ import annotations

OTC_MARKET_MAP = {
    "EURUSD OTC": "EURUSD_otc",
    "GBPUSD OTC": "GBPUSD_otc",
    "USDJPY OTC": "USDJPY_otc",
    "AUDUSD OTC": "AUDUSD_otc",
    "GBPJPY OTC": "GBPJPY_otc",
    "EURJPY OTC": "EURJPY_otc",
    "EURGBP OTC": "EURGBP_otc",
    "EURCHF OTC": "EURCHF_otc",
    "EURCAD OTC": "EURCAD_otc",
    "EURAUD OTC": "EURAUD_otc",
    "AUDJPY OTC": "AUDJPY_otc",
    "AUDCHF OTC": "AUDCHF_otc",
    "AUDCAD OTC": "AUDCAD_otc",
    "AUDNZD OTC": "AUDNZD_otc",
    "GBPAUD OTC": "GBPAUD_otc",
    "GBPCAD OTC": "GBPCAD_otc",
    "GBPCHF OTC": "GBPCHF_otc",
    "NZDUSD OTC": "NZDUSD_otc",
    "NZDJPY OTC": "NZDJPY_otc",
    "NZDCHF OTC": "NZDCHF_otc",
    "USDCAD OTC": "USDCAD_otc",
    "USDCHF OTC": "USDCHF_otc",
    "USDMXN OTC": "USDMXN_otc",
    "USDINR OTC": "USDINR_otc",
    "USDARS OTC": "USDARS_otc",
}

OTC_PAIRS = tuple(OTC_MARKET_MAP.values())
OTC_DISPLAY_PAIRS = tuple(OTC_MARKET_MAP.keys())


def display_for_asset(asset: str) -> str | None:
    value = str(asset or "").strip()
    for label, symbol in OTC_MARKET_MAP.items():
        if value.lower() == symbol.lower():
            return label
    return None


def asset_for_display(pair: str) -> str | None:
    value = str(pair or "").strip().upper()
    return OTC_MARKET_MAP.get(value)


def normalize_detected_market(text: str) -> str | None:
    """Map visible Quotex market text to a supported *_otc symbol.

    Examples accepted: ``AUD/USD (OTC)``, ``AUDUSD OTC`` and
    ``AUDUSD_otc``. The OTC marker is required so a normal Real market cannot
    accidentally enter the OTC stream.
    """
    raw = str(text or "").upper()
    compact = "".join(ch for ch in raw if ch.isalnum())
    if "OTC" not in compact:
        return None
    for symbol in OTC_PAIRS:
        base = symbol[:-4].upper()
        if base in compact and "OTC" in compact:
            return symbol
    return None
