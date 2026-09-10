import os
from pathlib import Path

import webview

APP_URL = os.getenv("MMC_APP_URL", "https://mmc-treading-bot.onrender.com/")

# WebView2 must reuse the same writable user-data folder between launches.
# pywebview otherwise defaults to private mode, which discards cookies/localStorage
# when the desktop app closes. That was causing both Remember Me and the stable
# Master device ID to disappear on every restart.
APP_DATA = Path(os.getenv("APPDATA") or Path.home()) / "MMC-Trading-Bot"
WEBVIEW_DATA = APP_DATA / "WebView2"
WEBVIEW_DATA.mkdir(parents=True, exist_ok=True)

if __name__ == "__main__":
    webview.create_window(
        "MMC Live Signal",
        APP_URL,
        width=1280,
        height=820,
        min_size=(900, 600),
        text_select=True,
    )
    webview.start(
        gui="edgechromium",
        debug=False,
        private_mode=False,
        storage_path=str(WEBVIEW_DATA),
    )
